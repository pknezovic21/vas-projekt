import logging
from collections import deque

from sim.agents.base import BaseAgent
from sim.agents.behaviours import MessageReceiver, OneShotCall
from sim.protocol import (
    MSG_REGISTER,
    MSG_RESOURCE_REQUEST,
    MSG_DISPATCH,
    MSG_SHUTDOWN,
    MSG_VEHICLE_STATUS,
)
from sim.utils import allocate_resources, jid_user, normalize_resources, resource_phrase, subtract_resources, total_resources


LOGGER = logging.getLogger(__name__)


class AidCenterAgent(BaseAgent):
    def __init__(
        self,
        jid,
        password,
        config,
        center_id,
        location,
        inventory,
        world_jid,
        vehicle_jids,
        vehicle_capacities,
    ):
        super().__init__(jid, password, config)
        self.center_id = center_id
        self.location = location
        self.world_jid = world_jid
        self.inventory = normalize_resources(inventory)
        self.vehicle_jids = list(vehicle_jids)
        self.vehicle_capacities = dict(vehicle_capacities)
        self.available_vehicles = set(vehicle_jids)
        self.pending_requests = deque()
        self.priority_order = ("med", "water", "food")

    async def setup(self):
        self.add_behaviour(OneShotCall("on_start"))
        self.add_behaviour(MessageReceiver())

    async def on_start(self):
        payload = {
            "agent_type": "center",
            "jid": str(self.jid),
            "center_id": self.center_id,
            "location": self.location,
        }
        await self.send_typed(self.world_jid, MSG_REGISTER, payload)

    async def on_message(self, msg_type, payload, sender):
        if msg_type == MSG_RESOURCE_REQUEST:
            self.pending_requests.append(payload)
            await self._try_dispatch()
        elif msg_type == MSG_VEHICLE_STATUS:
            self._update_vehicle_status(payload)
            await self._try_dispatch()
        elif msg_type == MSG_SHUTDOWN:
            await self.stop()

    async def _try_dispatch(self):
        if not self.available_vehicles or not self.pending_requests:
            return

        requests = deque()
        while self.pending_requests and self.available_vehicles:
            request = self.pending_requests.popleft()
            vehicle_jid = sorted(self.available_vehicles)[0]
            capacity = self.vehicle_capacities.get(vehicle_jid, 0)
            shipment = allocate_resources(self.inventory, request.get("needs", {}), capacity, priority=self.priority_order)
            used_capacity = total_resources(shipment)
            if used_capacity <= 0:
                requests.append(request)
                continue

            self.inventory = subtract_resources(self.inventory, shipment)
            self.available_vehicles.remove(vehicle_jid)

            payload = {
                "center_id": self.center_id,
                "origin": self.location,
                "destination": request.get("location"),
                "group_jid": request.get("group_jid"),
                "group_id": request.get("group_id"),
                "resources": shipment,
                "request_id": request.get("request_id"),
            }
            await self.send_typed(vehicle_jid, MSG_DISPATCH, payload)
            LOGGER.info(
                f"Center {self.center_id} at {self.location} dispatched vehicle {jid_user(vehicle_jid)} to {payload['destination']} "
                f"for group {payload.get('group_id')} (request {payload.get('request_id')}). Loaded: {resource_phrase(shipment)} "
                f"(capacity {capacity}, used {used_capacity}). Inventory left: {resource_phrase(self.inventory, include_zero=True)}."
            )

        while requests:
            self.pending_requests.append(requests.popleft())

    def _update_vehicle_status(self, payload):
        status = payload.get("status")
        vehicle_jid = payload.get("jid")
        if status == "idle" and vehicle_jid in self.vehicle_jids:
            self.available_vehicles.add(vehicle_jid)
