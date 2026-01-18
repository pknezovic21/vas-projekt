import logging

from sim.agents.base import BaseAgent
from sim.agents.behaviours import MessageReceiver, OneShotCall, PeriodicCall
from sim.pathfinding import dijkstra
from sim.protocol import (
    MSG_ATTACK,
    MSG_DISPATCH,
    MSG_REGISTER,
    MSG_SHUTDOWN,
    MSG_VEHICLE_STATUS,
    MSG_WORLD_UPDATE,
    MSG_DELIVERY,
)
from sim.utils import normalize_resources, resource_phrase


LOGGER = logging.getLogger(__name__)


class VehicleAgent(BaseAgent):
    def __init__(
        self,
        jid,
        password,
        config,
        vehicle_id,
        home_location,
        home_center_jid,
        capacity,
        world_jid,
        base_edges,
        adjacency,
    ):
        super().__init__(jid, password, config)
        self.vehicle_id, self.world_jid = vehicle_id, world_jid
        self.home_location, self.home_center_jid = home_location, home_center_jid
        self.capacity, self.base_edges, self.adjacency = int(capacity), base_edges, adjacency
        self.location, self.status = home_location, "idle"
        self.cargo = normalize_resources({})
        self.destination = self.group_jid = self.group_id = self.request_id = None
        self.route, self.edge_remaining = [], 0
        self.known_closed, self.known_delays = set(), {}
        self.pending_delay = 0

    async def setup(self):
        tick_seconds = int(self.config.simulation.get("tick_seconds", 1))
        self.add_behaviour(OneShotCall("on_start"))
        self.add_behaviour(MessageReceiver())
        self.add_behaviour(PeriodicCall("on_tick", period=tick_seconds))

    async def on_start(self):
        payload = {
            "agent_type": "vehicle",
            "jid": str(self.jid),
            "vehicle_id": self.vehicle_id,
            "location": self.location,
        }
        await self.send_typed(self.world_jid, MSG_REGISTER, payload)
        await self._send_status(to_center=False)

    async def on_message(self, msg_type, payload, sender):
        if msg_type == MSG_DISPATCH:
            self.destination = payload.get("destination")
            self.group_jid = payload.get("group_jid")
            self.group_id = payload.get("group_id")
            self.request_id = payload.get("request_id")
            self.cargo = normalize_resources(payload.get("resources", {}))
            self.status = "en_route"
            self.route = []
            self.edge_remaining = 0
            LOGGER.info(
                f"Vehicle {self.vehicle_id} started from {self.location} to {self.destination} for group {self.group_id} "
                f"(request {self.request_id}). Cargo: {resource_phrase(self.cargo)}."
            )
            self._plan_route()
            await self._send_status()
        elif msg_type == MSG_WORLD_UPDATE:
            self._update_world(payload)
        elif msg_type == MSG_ATTACK:
            delay = int(payload.get("delay", 0))
            loss = float(payload.get("loss", 0))
            if delay > 0:
                if self.status in ("en_route", "returning") and self.edge_remaining > 0:
                    self.edge_remaining += delay
                else:
                    self.pending_delay += delay
            if loss > 0 and self.status in ("en_route", "returning"):
                for key in self.cargo:
                    self.cargo[key] = max(0, int(self.cargo[key] * (1 - loss)))
            LOGGER.info(
                f"Vehicle {self.vehicle_id} was attacked (request {self.request_id}): delay +{delay}, loss {loss * 100:.0f}%. "
                f"Cargo now: {resource_phrase(self.cargo)}."
            )
        elif msg_type == MSG_SHUTDOWN:
            await self.stop()

    async def on_tick(self):
        if self.status not in ("en_route", "returning"):
            return

        if self.location == self.destination:
            await (self._deliver() if self.status == "en_route" else self._arrive_home())
            return

        if self.edge_remaining > 0:
            self.edge_remaining -= 1
            if self.edge_remaining > 0:
                return

            if self.route:
                self.location = self.route.pop(0)
            await self._send_status()

        if self.location == self.destination:
            await (self._deliver() if self.status == "en_route" else self._arrive_home())
            return

        if not self.route:
            self._plan_route()
            if not self.route:
                return
        edge = (self.location, self.route[0])
        if edge in self.known_closed or edge not in self.base_edges:
            self.route = []
            return
        travel_time = int(self.base_edges[edge]) + int(self.known_delays.get(edge, 0)) + self.pending_delay
        self.pending_delay = 0
        self.edge_remaining = max(1, travel_time)

    def _plan_route(self):
        if not self.destination or self.location == self.destination:
            self.route = []
            return
        path, _ = dijkstra(
            self.location,
            self.destination,
            self.adjacency,
            self.base_edges,
            self.known_closed,
            self.known_delays,
        )
        self.route = path[1:] if path else []

    async def _send_status(self, *, to_center: bool = True):
        payload = {
            "jid": str(self.jid),
            "vehicle_id": self.vehicle_id,
            "status": self.status,
            "location": self.location,
        }
        await self.send_typed(self.world_jid, MSG_VEHICLE_STATUS, payload)
        if to_center:
            await self.send_typed(self.home_center_jid, MSG_VEHICLE_STATUS, payload)

    async def _deliver(self):
        if not self.group_jid:
            return
        payload = {
            "vehicle_id": self.vehicle_id,
            "resources": self.cargo,
            "from": self.home_center_jid,
            "request_id": self.request_id,
        }
        await self.send_typed(self.group_jid, MSG_DELIVERY, payload)
        LOGGER.info(
            f"Vehicle {self.vehicle_id} delivered to group {self.group_id} at {self.location} (request {self.request_id}): "
            f"{resource_phrase(self.cargo)}."
        )
        self.cargo = normalize_resources({})
        self.destination, self.status = self.home_location, "returning"
        self.route, self.edge_remaining = [], 0
        self._plan_route()
        await self._send_status()

    async def _arrive_home(self):
        self.status, self.destination = "idle", None
        self.group_jid = self.group_id = self.request_id = None
        self.route, self.edge_remaining = [], 0
        await self._send_status()
        LOGGER.info(f"Vehicle {self.vehicle_id} returned to base ({self.home_location}).")

    def _update_world(self, payload):
        self.known_closed = {(e["from"], e["to"]) for e in payload.get("closed_edges", [])}
        self.known_delays = {(e["from"], e["to"]): int(e["extra"]) for e in payload.get("delays", [])}
