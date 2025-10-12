from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from botman.core.api.models import Bank as BankModel


# Request Messages (Incoming to Bank)


# General operations
@dataclass
class GetBankInfoMessage:
    """Request current bank state."""
    pass


@dataclass
class RefreshBankMessage:
    """Request to refresh bank state from API."""
    pass


# Item operations
@dataclass
class CheckItemMessage:
    """Check if item is available in bank."""
    code: str
    quantity: int


@dataclass
class ReserveItemMessage:
    """Reserve items for withdrawal."""
    code: str
    quantity: int
    bot_name: str


@dataclass
class ReleaseReservationMessage:
    """Release an item reservation."""
    reservation_id: str


@dataclass
class UpdateAfterWithdrawMessage:
    """Update bank state after successful withdrawal."""
    reservation_id: str
    actual_quantity: int


@dataclass
class UpdateAfterDepositMessage:
    """Update bank state after successful deposit."""
    items: List[Dict[str, Any]]  # [{"code": "item", "quantity": 1}, ...]


# Gold operations
@dataclass
class CheckGoldMessage:
    """Check if gold is available in bank."""
    quantity: int


@dataclass
class ReserveGoldMessage:
    """Reserve gold for withdrawal."""
    quantity: int
    bot_name: str


@dataclass
class ReleaseGoldReservationMessage:
    """Release a gold reservation."""
    reservation_id: str


@dataclass
class UpdateAfterGoldWithdrawMessage:
    """Update bank state after successful gold withdrawal."""
    reservation_id: str
    actual_quantity: int


@dataclass
class UpdateAfterGoldDepositMessage:
    """Update bank state after successful gold deposit."""
    quantity: int


# Response Messages (Outgoing from Bank)


@dataclass
class GetBankInfoResponse:
    """Response containing bank state."""
    bank: Optional[BankModel]
    items: Dict[str, int]
    item_reservations: Dict[str, Dict[str, Tuple[str, int]]]
    gold_reservations: Dict[str, Tuple[str, int]]


@dataclass
class RefreshBankResponse:
    """Response to refresh request."""
    success: bool


@dataclass
class CheckItemResponse:
    """Response to item availability check."""
    available: bool
    total_in_bank: int
    reserved: int
    free: int
    requested: int


@dataclass
class ReserveItemResponse:
    """Response to item reservation request."""
    success: bool
    reservation_id: str = ""
    reserved: int = 0
    item_code: str = ""
    bot_name: str = ""
    error: str = ""
    details: Optional[Dict[str, Any]] = None


@dataclass
class ReleaseReservationResponse:
    """Response to reservation release."""
    success: bool
    item_code: str = ""
    quantity: int = 0
    bot_name: str = ""
    error: str = ""


@dataclass
class UpdateAfterWithdrawResponse:
    """Response to post-withdrawal update."""
    success: bool
    item_code: str = ""
    reserved_quantity: int = 0
    actual_quantity: int = 0
    new_quantity: int = 0
    error: str = ""


@dataclass
class UpdateAfterDepositResponse:
    """Response to post-deposit update."""
    success: bool
    deposited: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.deposited is None:
            self.deposited = []


@dataclass
class CheckGoldResponse:
    """Response to gold availability check."""
    available: bool
    total_in_bank: int
    reserved: int
    free: int
    requested: int


@dataclass
class ReserveGoldResponse:
    """Response to gold reservation request."""
    success: bool
    reservation_id: str = ""
    reserved: int = 0
    bot_name: str = ""
    error: str = ""
    details: Optional[Dict[str, Any]] = None


@dataclass
class ReleaseGoldReservationResponse:
    """Response to gold reservation release."""
    success: bool
    quantity: int = 0
    bot_name: str = ""
    error: str = ""


@dataclass
class UpdateAfterGoldWithdrawResponse:
    """Response to post-gold-withdrawal update."""
    success: bool
    reserved_quantity: int = 0
    actual_quantity: int = 0
    new_quantity: int = 0
    error: str = ""


@dataclass
class UpdateAfterGoldDepositResponse:
    """Response to post-gold-deposit update."""
    success: bool
    deposited: int = 0
    new_total: int = 0
    error: str = ""
