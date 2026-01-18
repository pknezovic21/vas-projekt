import logging

from sim.agents.base import BaseAgent
from sim.agents.behaviours import MessageReceiver, OneShotCall, PeriodicCall
from sim.protocol import (
    MSG_DEMAND_UPDATE,
    MSG_DELIVERY,
    MSG_REGISTER,
    MSG_RESOURCE_REQUEST,
    MSG_SHUTDOWN,
)
from sim.utils import (
    add_resources,
    clamp_resources,
    jid_user,
    normalize_resources,
    resource_diff,
    resource_phrase,
    subtract_resources,
    total_resources,
)


LOGGER = logging.getLogger(__name__)


class AidGroupAgent(BaseAgent):
    def __init__(
        self,
        jid,
        password,
        config,
        group_id,
        location,
        assigned_center_jid,
        stock,
        min_threshold,
        max_capacity,
        consumption_per_tick,
        world_jid,
    ):
        super().__init__(jid, password, config)
        self.group_id = group_id
        self.location = location
        self.assigned_center_jid = assigned_center_jid
        self.world_jid = world_jid

        self.stock = normalize_resources(stock)
        self.min_threshold = normalize_resources(min_threshold)
        self.max_capacity = normalize_resources(max_capacity)
        self.consumption_per_tick = normalize_resources(consumption_per_tick)
        self.request_cooldown = int(self.config.simulation.get("request_cooldown", 3))
        self.last_request_tick = -self.request_cooldown
        self.request_seq = 0
        self.pending_request_id = None
        self.tick = 0

    async def setup(self):
        tick_seconds = int(self.config.simulation.get("tick_seconds", 1))
        self.add_behaviour(OneShotCall("on_start"))
        self.add_behaviour(PeriodicCall("on_tick", period=tick_seconds))
        self.add_behaviour(MessageReceiver())

    async def on_start(self):
        payload = {
            "agent_type": "group",
            "jid": str(self.jid),
            "group_id": self.group_id,
            "location": self.location,
        }
        await self.send_typed(self.world_jid, MSG_REGISTER, payload)

    async def on_tick(self):
        self.tick += 1
        self.stock = subtract_resources(self.stock, self.consumption_per_tick)
        await self._maybe_request()

    async def on_message(self, msg_type, payload, sender):
        if msg_type == MSG_DELIVERY:
            request_id = payload.get("request_id")
            source = payload.get("from")
            resources = normalize_resources(payload.get("resources", {}))
            self.stock = add_resources(self.stock, resources)
            self.stock = clamp_resources(self.stock, self.max_capacity)
            self.pending_request_id = None
            LOGGER.info(
                f"Group {self.group_id} at {self.location} received delivery for request {request_id} from center {jid_user(source)}: "
                f"{resource_phrase(resources)}. Stock now: {resource_phrase(self.stock, include_zero=True)}."
            )
        elif msg_type == MSG_DEMAND_UPDATE:
            amounts = normalize_resources(payload.get("amounts", {}))
            self.stock = subtract_resources(self.stock, amounts)
            LOGGER.info(
                f"Group {self.group_id} at {self.location} had a sudden demand spike (consumed: {resource_phrase(amounts)}). "
                f"Stock now: {resource_phrase(self.stock, include_zero=True)}."
            )
        elif msg_type == MSG_SHUTDOWN:
            await self.stop()

    async def _maybe_request(self):
        if self.pending_request_id is not None or self.tick - self.last_request_tick < self.request_cooldown or not any(
            self.stock[k] < self.min_threshold[k] for k in self.stock
        ):
            return
        need = resource_diff(self.max_capacity, self.stock)
        if total_resources(need) <= 0:
            return
        self.request_seq += 1
        request_id = f"{self.group_id}:{self.request_seq:03d}"
        payload = {
            "group_id": self.group_id,
            "group_jid": str(self.jid),
            "location": self.location,
            "needs": need,
            "request_id": request_id,
        }
        await self.send_typed(self.assigned_center_jid, MSG_RESOURCE_REQUEST, payload)
        self.last_request_tick = self.tick
        self.pending_request_id = request_id
        LOGGER.info(
            f"Group {self.group_id} at {self.location} sent request {request_id} to center {jid_user(self.assigned_center_jid)}. "
            f"Needs: {resource_phrase(need)}. Current stock: {resource_phrase(self.stock, include_zero=True)}."
        )
