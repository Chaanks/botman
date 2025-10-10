"""
UIBridge actor for managing UI state and broadcasting updates.

Replaces the PubSub broker with a centralized state management actor.
"""

import asyncio
from typing import Any, Dict, List, Optional
from actor import Actor


class UIBridge(Actor):
    """
    Central state management actor for the UI.

    Manages bot states and logs, and broadcasts updates to all subscribers.
    Subscribers receive updates via asyncio.Queue objects.
    """

    def __init__(self):
        super().__init__()

        # State management
        self.state: Dict[str, Any] = {
            'bots': {},      # Dict[str, BotState]
            'logs': [],      # List[LogEntry] (max 100)
        }

        # Subscriber management
        self.subscribers: List[asyncio.Queue] = []

    async def on_receive(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Handle incoming messages.

        Supported message types:
        - bot_changed: Update bot state and broadcast
        - log: Add log entry and broadcast
        - get_state: Return current state
        - subscribe: Add subscriber queue
        """
        msg_type = message.get('type')

        if msg_type == 'bot_changed':
            return await self._handle_bot_changed(message)

        elif msg_type == 'log':
            return await self._handle_log(message)

        elif msg_type == 'get_state':
            return await self._handle_get_state(message)

        elif msg_type == 'subscribe':
            return await self._handle_subscribe(message)

        else:
            print(f"UIBridge: Unknown message type: {msg_type}")
            return None

    async def _handle_bot_changed(self, message: Dict[str, Any]) -> None:
        """Handle bot state update."""
        bot_name = message.get('bot_name')
        bot_data = message.get('data')

        if not bot_name or not bot_data:
            print("UIBridge: Invalid bot_changed message - missing bot_name or data")
            return None

        # Update state
        self.state['bots'][bot_name] = bot_data

        # Broadcast update
        await self._broadcast(('bot_changed', {
            'bot_name': bot_name,
            'data': bot_data
        }))

        return None

    async def _handle_log(self, message: Dict[str, Any]) -> None:
        """Handle log entry."""
        log_entry = {
            'level': message.get('level', 'INFO'),
            'source': message.get('source', 'system'),
            'message': message.get('message', ''),
            'timestamp': message.get('timestamp', 0),
        }

        # Append to logs
        self.state['logs'].append(log_entry)

        # Trim to 100 entries
        if len(self.state['logs']) > 100:
            self.state['logs'] = self.state['logs'][-100:]

        # Broadcast update
        await self._broadcast(('log', log_entry))

        return None

    async def _handle_get_state(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Return full state dict."""
        return self.state.copy()

    async def _handle_subscribe(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Add subscriber queue."""
        queue = message.get('queue')

        if not isinstance(queue, asyncio.Queue):
            return {'success': False, 'error': 'Invalid queue object'}

        self.subscribers.append(queue)

        return {
            'success': True,
            'subscriber_count': len(self.subscribers)
        }

    async def _broadcast(self, update: tuple) -> None:
        """
        Broadcast update to all subscribers.

        Args:
            update: Tuple of (event_type, data)
        """
        dead_queues = []

        # Iterate through all subscriber queues
        for queue in self.subscribers:
            try:
                # Use put_nowait to avoid blocking
                queue.put_nowait(update)
            except asyncio.QueueFull:
                # Queue is full, mark for removal
                dead_queues.append(queue)
            except Exception as e:
                # Other errors, mark for removal
                print(f"UIBridge: Error broadcasting to subscriber: {e}")
                dead_queues.append(queue)

        # Remove dead queues
        for dead_queue in dead_queues:
            try:
                self.subscribers.remove(dead_queue)
            except ValueError:
                pass  # Already removed

    async def on_start(self):
        """Lifecycle hook called when actor starts."""
        print("UIBridge: Started")

    async def on_stop(self):
        """Lifecycle hook called when actor stops."""
        print("UIBridge: Stopped")

        # Clear all subscribers
        self.subscribers.clear()