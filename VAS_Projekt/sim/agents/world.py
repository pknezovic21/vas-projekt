import logging
import random

from sim.agents.base import BaseAgent
from sim.agents.behaviours import MessageReceiver, PeriodicCall
from sim.protocol import (
    MSG_ATTACK,
    MSG_DEMAND_UPDATE,
    MSG_REGISTER,
    MSG_SHUTDOWN,
    MSG_VEHICLE_STATUS,
    MSG_WORLD_UPDATE,
)
from sim.utils import normalize_resources


LOGGER = logging.getLogger(__name__)


class WorldAgent(BaseAgent):
    def __init__(self, jid, password, config):
        super().__init__(jid, password, config)
        self.map_data = config.map_data
        self.events = config.events
        self.tick_seconds = int(config.simulation.get("tick_seconds", 1))
        self.max_ticks = int(config.simulation.get("max_ticks", 60))
        self.random = random.Random(config.simulation.get("random_seed", 0))

        self.tick = 0
        self.closed_edges = {}
        self.delay_edges = {}
        self.registered = {"center": set(), "vehicle": set(), "group": set()}
        self.vehicle_status = {}

    async def setup(self):
        self.add_behaviour(PeriodicCall("on_tick", period=self.tick_seconds))
        self.add_behaviour(MessageReceiver())

    async def on_tick(self):
        self.tick += 1
        self._decrement_events()
        await self._maybe_close_road()
        await self._maybe_add_delay()
        await self._maybe_attack()
        await self._maybe_demand_spike()
        await self._broadcast_update()

        if self.tick >= self.max_ticks:
            await self._broadcast_shutdown()
            await self.stop()

    async def on_message(self, msg_type, payload, sender):
        if msg_type == MSG_REGISTER:
            await self._handle_register(payload, sender)
        elif msg_type == MSG_VEHICLE_STATUS:
            await self._handle_vehicle_status(payload, sender)

    def _get_prob(self, key, default):
        return float(self.events.get(key, default))

    def _get_range(self, key, default_min, default_max):
        value = self.events.get(key, [default_min, default_max])
        return int(value[0]), int(value[1])

    def _world_update_payload(self):
        return {
            "tick": self.tick,
            "closed_edges": [{"from": a, "to": b, "ttl": ttl} for (a, b), ttl in self.closed_edges.items()],
            "delays": [{"from": a, "to": b, "extra": i["extra"], "ttl": i["ttl"]} for (a, b), i in self.delay_edges.items()],
        }

    async def _broadcast_update(self):
        payload = self._world_update_payload()
        for jid in self.registered.get("vehicle", set()):
            await self.send_typed(jid, MSG_WORLD_UPDATE, payload)

    async def _broadcast_shutdown(self):
        payload = {"tick": self.tick}
        for jid in set().union(*self.registered.values()):
            await self.send_typed(jid, MSG_SHUTDOWN, payload)

    def _decrement_events(self):
        for edge in list(self.closed_edges):
            ttl = self.closed_edges[edge] - 1
            if ttl <= 0:
                self.closed_edges.pop(edge, None)
            else:
                self.closed_edges[edge] = ttl
        for edge in list(self.delay_edges):
            ttl = self.delay_edges[edge]["ttl"] - 1
            if ttl <= 0:
                self.delay_edges.pop(edge, None)
            else:
                self.delay_edges[edge]["ttl"] = ttl

    async def _maybe_close_road(self):
        if self.map_data.roads and self.random.random() <= self._get_prob("road_close_prob", 0.1):
            road = self.random.choice(self.map_data.roads)
            ttl = self.random.randint(*self._get_range("road_close_duration", 2, 5))
            self._apply_closure(road, ttl)
            LOGGER.info(f"Road {road['from']} -> {road['to']} is closed (for {ttl} ticks).")

    async def _maybe_add_delay(self):
        if self.map_data.roads and self.random.random() <= self._get_prob("delay_prob", 0.1):
            road = self.random.choice(self.map_data.roads)
            ttl = self.random.randint(*self._get_range("delay_duration", 2, 4))
            extra = self.random.randint(*self._get_range("delay_amount", 1, 3))
            self._apply_delay(road, extra, ttl)
            LOGGER.info(f"Traffic on road {road['from']} -> {road['to']}: +{extra} travel time (for {ttl} more ticks).")

    async def _maybe_attack(self):
        prob = self._get_prob("attack_prob", 0.05)
        if self.random.random() > prob or not self.vehicle_status:
            return
        candidates = [jid for jid, info in self.vehicle_status.items() if info.get("status") in ("en_route", "returning")]
        if not candidates:
            return
        target = self.random.choice(candidates)
        delay_min, delay_max = self._get_range("attack_delay", 1, 3)
        loss_min, loss_max = self.events.get("attack_loss", [0.1, 0.3])
        payload = {
            "delay": self.random.randint(delay_min, delay_max),
            "loss": self.random.uniform(float(loss_min), float(loss_max)),
        }
        await self.send_typed(target, MSG_ATTACK, payload)

    async def _maybe_demand_spike(self):
        prob = self._get_prob("demand_spike_prob", 0.1)
        groups = list(self.registered.get("group", []))
        if self.random.random() > prob or not groups:
            return
        target = self.random.choice(groups)
        amount_min, amount_max = self._get_range("demand_spike_amount", 5, 20)
        amount = self.random.randint(amount_min, amount_max)
        payload = {"amounts": normalize_resources({"food": amount, "water": amount, "med": amount})}
        await self.send_typed(target, MSG_DEMAND_UPDATE, payload)

    def _apply_closure(self, road, ttl):
        a, b = road["from"], road["to"]
        self.closed_edges[(a, b)] = ttl
        if road.get("bidirectional", True):
            self.closed_edges[(b, a)] = ttl

    def _apply_delay(self, road, extra, ttl):
        a, b = road["from"], road["to"]
        self.delay_edges[(a, b)] = {"extra": extra, "ttl": ttl}
        if road.get("bidirectional", True):
            self.delay_edges[(b, a)] = {"extra": extra, "ttl": ttl}

    async def _handle_register(self, payload, sender):
        agent_type = payload.get("agent_type")
        if agent_type in self.registered:
            self.registered[agent_type].add(sender)
            if agent_type == "vehicle":
                await self._send_initial_update(sender)

    async def _send_initial_update(self, jid):
        await self.send_typed(jid, MSG_WORLD_UPDATE, self._world_update_payload())

    async def _handle_vehicle_status(self, payload, sender):
        self.vehicle_status[sender] = {"status": payload.get("status"), "location": payload.get("location")}
