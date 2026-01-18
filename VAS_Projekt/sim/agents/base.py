from spade.agent import Agent
from spade.message import Message

from sim.protocol import make_message


class BaseAgent(Agent):
    def __init__(self, jid, password, config):
        xmpp = getattr(config, "xmpp", {}) or {}
        super().__init__(jid, password, port=int(xmpp.get("port", 5222)), verify_security=bool(xmpp.get("verify_security", False)))
        self.config = config

    async def send(self, msg: Message) -> None:
        if msg.empty_sender():
            msg.sender = str(self.jid)
        await self.container.send(msg, self)
        msg.sent = True
        self.traces.append(msg, category=str(self))

    async def send_typed(self, to, msg_type, payload) -> None:
        await self.send(make_message(to, msg_type, payload))
