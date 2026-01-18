from spade.behaviour import CyclicBehaviour, OneShotBehaviour, PeriodicBehaviour

from sim.protocol import parse_message


class OneShotCall(OneShotBehaviour):
    def __init__(self, method_name: str):
        super().__init__()
        self.method_name = method_name

    async def run(self):
        await getattr(self.agent, self.method_name)()


class PeriodicCall(PeriodicBehaviour):
    def __init__(self, method_name: str, *, period: float):
        super().__init__(period=period)
        self.method_name = method_name

    async def run(self):
        handler = getattr(self.agent, self.method_name, None)
        if handler is not None:
            await handler()


class MessageReceiver(CyclicBehaviour):
    def __init__(self, *, timeout: float = 1):
        super().__init__()
        self.timeout = timeout

    async def run(self):
        msg = await self.receive(timeout=self.timeout)
        if not msg:
            return
        msg_type, payload = parse_message(msg)
        await self.agent.on_message(msg_type, payload, sender=str(msg.sender))
