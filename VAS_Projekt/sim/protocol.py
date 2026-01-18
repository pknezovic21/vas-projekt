import json

from spade.message import Message


MSG_REGISTER = "register"
MSG_WORLD_UPDATE = "world_update"
MSG_RESOURCE_REQUEST = "resource_request"
MSG_DISPATCH = "dispatch"
MSG_DELIVERY = "delivery"
MSG_VEHICLE_STATUS = "vehicle_status"
MSG_ATTACK = "attack"
MSG_DEMAND_UPDATE = "demand_update"
MSG_SHUTDOWN = "shutdown"


def make_message(to, msg_type, payload):
    msg = Message(to=to)
    msg.set_metadata("type", msg_type)
    msg.body = json.dumps(payload)
    return msg


def parse_message(msg):
    return msg.get_metadata("type"), (json.loads(msg.body) if msg.body else {})
