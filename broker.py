import time
import threading
from collections import defaultdict
from queue import Queue
from dataclasses import dataclass
from typing import Any, Dict, Set, Optional
from enum import Enum

from models import Character


@dataclass
class Message:
    topic: str
    data: Any
    timestamp: float
    sender: Optional[str] = None


class PubSub:
    """Thread-safe PubSub broker"""

    def __init__(self):
        self._subscribers: Dict[str, Set[Queue]] = {}
        self._lock = threading.RLock()
        self._message_history: Dict[str, list] = defaultdict(list)
        self._max_history = 100

    def subscribe(self, topic: str) -> Queue:
        queue = Queue(maxsize=100)
        with self._lock:
            if topic not in self._subscribers:
                self._subscribers[topic] = set()
            self._subscribers[topic].add(queue)
        return queue

    def unsubscribe(self, topic: str, queue: Queue):
        """Unsubscribe from a topic"""
        with self._lock:
            if topic in self._subscribers:
                self._subscribers[topic].discard(queue)

    def publish(self, topic: str, data: Any, sender: Optional[str] = None):
        """Publish message to topic (thread-safe)"""
        message = Message(topic=topic, data=data, timestamp=time.time(), sender=sender)

        with self._lock:
            # Add to history
            self._message_history[topic].append(message)
            if len(self._message_history[topic]) > self._max_history:
                self._message_history[topic].pop(0)

            # Deliver to all subscribers
            if topic in self._subscribers:
                dead_queues = set()

                for queue in self._subscribers[topic]:
                    try:
                        queue.put_nowait(message)
                    except Exception:
                        # Queue full or closed, mark for removal
                        dead_queues.add(queue)

                # Clean up dead queues
                for queue in dead_queues:
                    self._subscribers[topic].discard(queue)

    def get_history(self, topic: str, limit: int = 10) -> list:
        """Get recent message history for a topic"""
        with self._lock:
            return self._message_history[topic][-limit:]

    def topics(self) -> Set[str]:
        """Get all active topics"""
        with self._lock:
            return set(self._subscribers.keys())


class MessageType(Enum):
    """Types of messages in the system"""

    TASK_CREATE = "task_create"
    BOT_UPDATE = "bot_update"
    LOG = "log"
    STATUS_REQUEST = "status_request"


@dataclass
class TaskMessage:
    """Request to create a task (TUI → Orchestrator)"""

    task_type: str  # 'hello', 'gather', 'fight', 'craft'
    params: Dict[str, Any]
    target_bot: Optional[str] = None
    priority: int = 1


@dataclass
class BotUpdateMessage:
    """Bot status update (Bot → TUI)"""

    bot_name: str
    status: str  # 'Idle', 'Busy', 'Cooldown'
    current_task: Optional[str]
    progress: str
    cooldown: int
    character: Character


@dataclass
class LogMessage:
    """Log message (Any → TUI)"""

    level: str  # 'INFO', 'WARN', 'ERROR', 'DEBUG'
    source: str
    message: str
    timestamp: float
