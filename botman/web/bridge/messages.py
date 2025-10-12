"""Type-safe messages for UIBridge actor communication."""

import asyncio
from dataclasses import dataclass
from typing import Any, Dict


# Request Messages (Incoming to UIBridge)


@dataclass
class BotChangedMessage:
    """Notification that a bot's state has changed."""
    bot_name: str
    data: Dict[str, Any]


@dataclass
class LogMessage:
    """Log message from a bot or system component."""
    level: str
    source: str
    message: str
    timestamp: float


@dataclass
class GetStateMessage:
    """Request to get current UI state."""
    pass


@dataclass
class SubscribeMessage:
    """Request to subscribe to UI updates."""
    queue: asyncio.Queue


@dataclass
class UnsubscribeMessage:
    """Request to unsubscribe from UI updates."""
    queue: asyncio.Queue


# Response Messages (Outgoing from UIBridge)


@dataclass
class GetStateResponse:
    """Response containing UI state."""
    state: Dict[str, Any]


@dataclass
class SubscribeResponse:
    """Response to subscription request."""
    success: bool
    subscriber_count: int = 0
    error: str = ""


@dataclass
class UnsubscribeResponse:
    """Response to unsubscription request."""
    success: bool
    subscriber_count: int = 0
    error: str = ""
