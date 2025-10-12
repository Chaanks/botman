import asyncio
import logging
from typing import Any, Dict, List
from functools import singledispatchmethod
from botman.core.actor import Actor
from botman.web.bridge.messages import (
    BotChangedMessage,
    LogMessage,
    GetStateMessage,
    GetStateResponse,
    SubscribeMessage,
    SubscribeResponse,
    UnsubscribeMessage,
    UnsubscribeResponse,
)

logger = logging.getLogger(__name__)


class UIBridge(Actor):
    """Manages UI state and broadcasts updates to subscribers."""

    def __init__(self, name: str = "ui", inbox_size: int = 200):
        super().__init__(name=name, inbox_size=inbox_size)
        self.state: Dict[str, Any] = {'bots': {}, 'logs': []}
        self.subscribers: List[asyncio.Queue] = []

    @singledispatchmethod
    async def on_receive(self, message) -> Any:
        """
        Handle incoming typed messages using singledispatch.

        All messages must be dataclass instances for type safety.
        """
        logger.warning(f"Unknown message type: {type(message)}")
        return None

    @on_receive.register
    async def _(self, msg: BotChangedMessage) -> None:
        """Handle bot status change notification."""
        if not msg.bot_name or not msg.data:
            logger.error("Invalid bot_changed message - missing bot_name or data")
            return None

        self.state['bots'][msg.bot_name] = msg.data
        await self._broadcast(('bot_changed', {'bot_name': msg.bot_name, 'data': msg.data}))
        return None

    @on_receive.register
    async def _(self, msg: LogMessage) -> None:
        """Handle log message."""
        log_entry = {
            'level': msg.level,
            'source': msg.source,
            'message': msg.message,
            'timestamp': msg.timestamp,
        }

        self.state['logs'].append(log_entry)
        if len(self.state['logs']) > 100:
            self.state['logs'] = self.state['logs'][-100:]

        await self._broadcast(('log', log_entry))
        return None

    @on_receive.register
    async def _(self, msg: GetStateMessage) -> GetStateResponse:
        """Handle state query request."""
        return GetStateResponse(state=self.state.copy())

    @on_receive.register
    async def _(self, msg: SubscribeMessage) -> SubscribeResponse:
        """Handle subscription request."""
        if not isinstance(msg.queue, asyncio.Queue):
            return SubscribeResponse(success=False, error='Invalid queue object')

        self.subscribers.append(msg.queue)
        return SubscribeResponse(success=True, subscriber_count=len(self.subscribers))

    @on_receive.register
    async def _(self, msg: UnsubscribeMessage) -> UnsubscribeResponse:
        """Handle unsubscription request."""
        if not isinstance(msg.queue, asyncio.Queue):
            return UnsubscribeResponse(success=False, error='Invalid queue object')

        try:
            self.subscribers.remove(msg.queue)
            return UnsubscribeResponse(success=True, subscriber_count=len(self.subscribers))
        except ValueError:
            return UnsubscribeResponse(
                success=False,
                error='Queue not found',
                subscriber_count=len(self.subscribers)
            )

    async def _broadcast(self, update: tuple) -> None:
        dead_queues = []
        for idx, queue in enumerate(self.subscribers):
            try:
                queue.put_nowait(update)
            except asyncio.QueueFull:
                logger.warning(f"Subscriber {idx} queue full ({queue.qsize()} items), disconnecting")
                dead_queues.append(queue)
            except Exception as e:
                logger.error(f"Error broadcasting to subscriber {idx}: {e}")
                dead_queues.append(queue)

        for dead_queue in dead_queues:
            try:
                self.subscribers.remove(dead_queue)
            except ValueError:
                pass

        if dead_queues:
            logger.info(f"Removed {len(dead_queues)} slow/failed subscribers")

    async def on_start(self):
        logger.info("UIBridge started")

    async def on_stop(self):
        logger.info("UIBridge stopped")
        self.subscribers.clear()