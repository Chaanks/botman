import asyncio
import logging
from typing import Any, Dict, List, Optional
from botman.core.actor import Actor

logger = logging.getLogger(__name__)


class UIBridge(Actor):
    """Manages UI state and broadcasts updates to subscribers."""

    def __init__(self):
        super().__init__()
        self.state: Dict[str, Any] = {'bots': {}, 'logs': []}
        self.subscribers: List[asyncio.Queue] = []

    async def on_receive(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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
            logger.warning(f"Unknown message type: {msg_type}")
            return None

    async def _handle_bot_changed(self, message: Dict[str, Any]) -> None:
        bot_name = message.get('bot_name')
        bot_data = message.get('data')

        if not bot_name or not bot_data:
            logger.error("Invalid bot_changed message - missing bot_name or data")
            return None

        self.state['bots'][bot_name] = bot_data
        await self._broadcast(('bot_changed', {'bot_name': bot_name, 'data': bot_data}))
        return None

    async def _handle_log(self, message: Dict[str, Any]) -> None:
        log_entry = {
            'level': message.get('level', 'INFO'),
            'source': message.get('source', 'system'),
            'message': message.get('message', ''),
            'timestamp': message.get('timestamp', 0),
        }

        self.state['logs'].append(log_entry)
        if len(self.state['logs']) > 100:
            self.state['logs'] = self.state['logs'][-100:]

        await self._broadcast(('log', log_entry))
        return None

    async def _handle_get_state(self, message: Dict[str, Any]) -> Dict[str, Any]:
        return self.state.copy()

    async def _handle_subscribe(self, message: Dict[str, Any]) -> Dict[str, Any]:
        queue = message.get('queue')
        if not isinstance(queue, asyncio.Queue):
            return {'success': False, 'error': 'Invalid queue object'}

        self.subscribers.append(queue)
        return {'success': True, 'subscriber_count': len(self.subscribers)}

    async def _broadcast(self, update: tuple) -> None:
        dead_queues = []
        for queue in self.subscribers:
            try:
                queue.put_nowait(update)
            except asyncio.QueueFull:
                dead_queues.append(queue)
            except Exception as e:
                logger.error(f"Error broadcasting to subscriber: {e}")
                dead_queues.append(queue)

        for dead_queue in dead_queues:
            try:
                self.subscribers.remove(dead_queue)
            except ValueError:
                pass

    async def on_start(self):
        logger.info("UIBridge started")

    async def on_stop(self):
        logger.info("UIBridge stopped")
        self.subscribers.clear()