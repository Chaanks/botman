"""
Lightweight async actor system inspired by Pykka.

Provides an asyncio-based actor model for concurrent message processing.
"""

import asyncio
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from dataclasses import dataclass


@dataclass
class _MessageEnvelope:
    """Internal wrapper for messages to support ask/tell patterns."""
    content: Dict[str, Any]
    reply_future: Optional[asyncio.Future] = None


class Actor(ABC):
    """
    Base class for async actors.

    Actors process messages sequentially from an inbox queue.
    Messages can be sent fire-and-forget (tell) or with a reply (ask).

    Example:
        class MyActor(Actor):
            async def on_receive(self, message: Dict) -> Optional[Dict]:
                if message['type'] == 'ping':
                    return {'type': 'pong'}
                return None

        actor = MyActor()
        await actor.start()
        await actor.tell({'type': 'ping'})
        response = await actor.ask({'type': 'ping'}, timeout=5.0)
        await actor.stop()
    """

    def __init__(self):
        """Initialize the actor with an empty inbox and stopped state."""
        self.inbox: asyncio.Queue[_MessageEnvelope] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._pending_asks: Dict[str, asyncio.Future] = {}

    async def start(self) -> None:
        """
        Start the actor's message processing loop.

        Creates the background task and calls the on_start() lifecycle hook.
        """
        if self._running:
            raise RuntimeError("Actor is already running")

        self._running = True
        self._task = asyncio.create_task(self._process_messages())

        # Call lifecycle hook
        await self.on_start()

    async def stop(self) -> None:
        """
        Gracefully stop the actor.

        Calls the on_stop() lifecycle hook, then cancels the message processing task.
        Waits for the task to complete cleanup.
        """
        if not self._running:
            return

        # Call lifecycle hook first
        await self.on_stop()

        self._running = False

        # Cancel the processing task
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Cancel any pending ask operations
        for future in self._pending_asks.values():
            if not future.done():
                future.cancel()
        self._pending_asks.clear()

    async def _process_messages(self) -> None:
        """
        Internal message processing loop.

        Continuously processes messages from the inbox queue until stopped.
        """
        try:
            while self._running:
                try:
                    # Wait for next message with timeout to allow checking _running flag
                    envelope = await asyncio.wait_for(
                        self.inbox.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue

                try:
                    # Process the message
                    result = await self.on_receive(envelope.content)

                    # If this was an ask, send the reply
                    if envelope.reply_future and not envelope.reply_future.done():
                        envelope.reply_future.set_result(result)

                except Exception as e:
                    # If this was an ask, propagate the exception
                    if envelope.reply_future and not envelope.reply_future.done():
                        envelope.reply_future.set_exception(e)
                    else:
                        # For tell messages, just log the error
                        # (in production you might want proper logging here)
                        print(f"Error processing message in {self.__class__.__name__}: {e}")

        except asyncio.CancelledError:
            # Clean shutdown
            pass

    @abstractmethod
    async def on_receive(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Handle incoming messages.

        Subclasses must implement this method to define message handling behavior.

        Args:
            message: The message to process

        Returns:
            Optional response dict (used when message was sent via ask())
        """
        raise NotImplementedError("Subclasses must implement on_receive()")

    async def tell(self, message: Dict[str, Any]) -> None:
        """
        Send a fire-and-forget message to this actor.

        The message is queued for processing but no reply is expected.

        Args:
            message: The message to send
        """
        if not self._running:
            raise RuntimeError("Actor is not running")

        envelope = _MessageEnvelope(content=message, reply_future=None)
        await self.inbox.put(envelope)

    async def ask(self, message: Dict[str, Any], timeout: float = 5.0) -> Any:
        """
        Send a message and wait for a reply.

        Args:
            message: The message to send
            timeout: Maximum time to wait for reply in seconds

        Returns:
            The response from the actor's on_receive() method

        Raises:
            asyncio.TimeoutError: If no reply received within timeout
            RuntimeError: If actor is not running
        """
        if not self._running:
            raise RuntimeError("Actor is not running")

        # Create a future for the reply
        reply_future = asyncio.Future()
        envelope = _MessageEnvelope(content=message, reply_future=reply_future)

        # Send the message
        await self.inbox.put(envelope)

        # Wait for reply with timeout
        try:
            result = await asyncio.wait_for(reply_future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            # Cancel the future if it's still pending
            if not reply_future.done():
                reply_future.cancel()
            raise

    async def on_start(self) -> None:
        """
        Lifecycle hook called when actor starts.
        """
        pass

    async def on_stop(self) -> None:
        """
        Lifecycle hook called when actor stops.
        """
        pass