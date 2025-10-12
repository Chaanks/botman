import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class _MessageEnvelope:
    """Envelope for actor messages - content can be any type."""

    content: Any
    reply_future: Optional[asyncio.Future] = None


class Actor(ABC):
    """Base class for async actors that process messages sequentially via ask/tell."""

    def __init__(self, name: Optional[str] = None, inbox_size: int = 100):
        self.name = name or self.__class__.__name__
        self.inbox: asyncio.Queue[_MessageEnvelope] = asyncio.Queue(maxsize=inbox_size)
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._pending_asks: Dict[str, asyncio.Future] = {}

    async def start(self) -> None:
        if self._running:
            raise RuntimeError("Actor is already running")

        self._running = True
        self._task = asyncio.create_task(self._process_messages())
        await self.on_start()

    async def stop(self) -> None:
        if not self._running:
            return

        await self.on_stop()
        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        for future in self._pending_asks.values():
            if not future.done():
                future.cancel()
        self._pending_asks.clear()

    async def _process_messages(self) -> None:
        try:
            while self._running:
                envelope = await self.inbox.get()

                try:
                    result = await self.on_receive(envelope.content)
                    if envelope.reply_future and not envelope.reply_future.done():
                        envelope.reply_future.set_result(result)
                except Exception as e:
                    if envelope.reply_future and not envelope.reply_future.done():
                        envelope.reply_future.set_exception(e)
                    else:
                        logger.error(
                            f"Error processing message in {self.name}: {e}"
                        )
        except asyncio.CancelledError:
            pass

    @abstractmethod
    async def on_receive(self, message: Any) -> Optional[Any]:
        """
        Handle incoming message.

        Message can be any type:
        - Dict (legacy)
        - Dataclass (typed messages)
        - Any other serializable object
        """
        raise NotImplementedError("Subclasses must implement on_receive()")

    async def tell(self, message: Any) -> None:
        """Send a fire-and-forget message (no response expected)."""
        if not self._running:
            raise RuntimeError("Actor is not running")
        envelope = _MessageEnvelope(content=message, reply_future=None)
        await self.inbox.put(envelope)

    async def ask(self, message: Any, timeout: float = 5.0) -> Any:
        """Send a message and wait for a response."""
        if not self._running:
            raise RuntimeError("Actor is not running")

        reply_future = asyncio.Future()
        envelope = _MessageEnvelope(content=message, reply_future=reply_future)
        await self.inbox.put(envelope)

        try:
            return await asyncio.wait_for(reply_future, timeout=timeout)
        except asyncio.TimeoutError:
            if not reply_future.done():
                reply_future.cancel()
            raise

    async def on_start(self) -> None:
        pass

    async def on_stop(self) -> None:
        pass
