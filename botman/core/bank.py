import asyncio
import logging
import uuid
from typing import Dict, Any, Optional, List
from collections import defaultdict
from botman.core.actor import Actor
from botman.core.api import ArtifactsClient
from botman.core.models import Bank, BankItem

logger = logging.getLogger("botman.bank")


class Bank(Actor):
    """
    Centralized bank management actor that coordinates bank access across all bots.

    Manages:
    - Bank state (gold, items)
    - Item and gold reservations to prevent concurrent withdrawal conflicts
    - Bank access authorization

    Message types:
    - get_bank_info: Returns current bank state

    Item operations:
    - check_item: Check if item is available (code, quantity)
    - reserve_item: Reserve items for withdrawal (code, quantity, bot_name) -> returns reservation_id
    - release_reservation: Release a reservation (reservation_id)
    - update_after_withdraw: Update state after withdrawal (reservation_id, actual_quantity)
    - update_after_deposit: Update state after deposit (items)

    Gold operations:
    - check_gold: Check if gold is available (quantity)
    - reserve_gold: Reserve gold for withdrawal (quantity, bot_name) -> returns reservation_id
    - release_gold_reservation: Release a gold reservation (reservation_id)
    - update_after_gold_withdraw: Update state after gold withdrawal (reservation_id, actual_quantity)
    - update_after_gold_deposit: Update state after gold deposit (quantity)

    - refresh: Force refresh bank state from API
    """

    def __init__(self, token: str):
        super().__init__()
        self.token = token
        self.api: Optional[ArtifactsClient] = None

        # Bank state
        self.bank: Optional[Bank] = None
        self.items: Dict[str, int] = {}  # item_code -> quantity

        # Item reservations: item_code -> {reservation_id: (bot_name, quantity)}
        self.item_reservations: Dict[str, Dict[str, tuple[str, int]]] = defaultdict(dict)

        # Gold reservations: {reservation_id: (bot_name, quantity)}
        self.gold_reservations: Dict[str, tuple[str, int]] = {}

        self._refresh_lock = asyncio.Lock()
        self.logger = logging.getLogger("botman.bank")

    async def on_start(self):
        """Initialize API client and load bank state"""
        self.logger.info("BankActor starting...")
        self.api = ArtifactsClient(self.token)
        await self._refresh_bank_state()
        self.logger.info(f"BankActor initialized: {self.bank.gold} gold, {len(self.items)} item types")

    async def on_stop(self):
        """Clean up resources"""
        self.logger.info("BankActor stopping...")
        if self.api:
            await self.api.close()

    async def on_receive(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process bank-related messages"""
        msg_type = message.get('type')

        # General
        if msg_type == 'get_bank_info':
            return await self._handle_get_bank_info()
        elif msg_type == 'refresh':
            await self._refresh_bank_state()
            return {'success': True}

        # Item operations
        elif msg_type == 'check_item':
            item_code = message.get('code')
            quantity = message.get('quantity', 1)
            return await self._handle_check_item(item_code, quantity)

        elif msg_type == 'reserve_item':
            item_code = message.get('code')
            quantity = message.get('quantity', 1)
            bot_name = message.get('bot_name')
            return await self._handle_reserve_item(item_code, quantity, bot_name)

        elif msg_type == 'release_reservation':
            reservation_id = message.get('reservation_id')
            return await self._handle_release_reservation(reservation_id)

        elif msg_type == 'update_after_withdraw':
            reservation_id = message.get('reservation_id')
            actual_quantity = message.get('actual_quantity')
            return await self._handle_update_after_withdraw(reservation_id, actual_quantity)

        elif msg_type == 'update_after_deposit':
            items = message.get('items', [])  # [{"code": "item", "quantity": 1}, ...]
            return await self._handle_update_after_deposit(items)

        # Gold operations
        elif msg_type == 'check_gold':
            quantity = message.get('quantity', 1)
            return await self._handle_check_gold(quantity)

        elif msg_type == 'reserve_gold':
            quantity = message.get('quantity', 1)
            bot_name = message.get('bot_name')
            return await self._handle_reserve_gold(quantity, bot_name)

        elif msg_type == 'release_gold_reservation':
            reservation_id = message.get('reservation_id')
            return await self._handle_release_gold_reservation(reservation_id)

        elif msg_type == 'update_after_gold_withdraw':
            reservation_id = message.get('reservation_id')
            actual_quantity = message.get('actual_quantity')
            return await self._handle_update_after_gold_withdraw(reservation_id, actual_quantity)

        elif msg_type == 'update_after_gold_deposit':
            quantity = message.get('quantity')
            return await self._handle_update_after_gold_deposit(quantity)

        else:
            self.logger.warning(f"Unknown message type: {msg_type}")
            return {'error': f'Unknown message type: {msg_type}'}

    async def _refresh_bank_state(self):
        """Refresh bank state from API (all items across pages)"""
        async with self._refresh_lock:
            try:
                # Get bank details (gold, slots, etc.)
                self.bank = await self.api.get_bank()

                # Get all bank items (paginated)
                self.items.clear()
                page = 1
                page_size = 100  # Max page size

                while True:
                    items_page = await self.api.get_bank_items(page=page, size=page_size)

                    if not items_page:
                        break

                    for item in items_page:
                        self.items[item.code] = item.quantity

                    # If we got fewer items than page size, we're done
                    if len(items_page) < page_size:
                        break

                    page += 1

                self.logger.debug(f"Bank refreshed: {self.bank.gold} gold, {len(self.items)} item types")
            except Exception as e:
                self.logger.error(f"Failed to refresh bank state: {e}")
                raise

    async def _handle_get_bank_info(self) -> Dict[str, Any]:
        """Return current bank state"""
        return {
            'bank': self.bank,
            'items': dict(self.items),
            'item_reservations': {
                code: {res_id: (bot, qty) for res_id, (bot, qty) in reservations.items()}
                for code, reservations in self.item_reservations.items()
            },
            'gold_reservations': dict(self.gold_reservations)
        }

    async def _handle_check_item(self, item_code: str, quantity: int) -> Dict[str, Any]:
        """Check if item is available (considering reservations)"""
        total_in_bank = self.items.get(item_code, 0)

        # Calculate reserved quantity
        reserved = sum(qty for _, qty in self.item_reservations.get(item_code, {}).values())

        available = total_in_bank - reserved
        is_available = available >= quantity

        return {
            'available': is_available,
            'total_in_bank': total_in_bank,
            'reserved': reserved,
            'free': available,
            'requested': quantity
        }

    async def _handle_reserve_item(self, item_code: str, quantity: int, bot_name: str) -> Dict[str, Any]:
        """Reserve items for withdrawal - returns reservation_id"""
        if not bot_name:
            return {'success': False, 'error': 'bot_name is required'}

        # Check availability
        check_result = await self._handle_check_item(item_code, quantity)

        if not check_result['available']:
            return {
                'success': False,
                'error': f'Insufficient items: requested {quantity}, available {check_result["free"]}',
                'details': check_result
            }

        # Create unique reservation ID
        reservation_id = str(uuid.uuid4())

        # Create reservation
        self.item_reservations[item_code][reservation_id] = (bot_name, quantity)
        self.logger.info(f"Reserved {quantity}x {item_code} for {bot_name} (reservation_id: {reservation_id})")

        return {
            'success': True,
            'reservation_id': reservation_id,
            'reserved': quantity,
            'item_code': item_code,
            'bot_name': bot_name
        }

    async def _handle_release_reservation(self, reservation_id: str) -> Dict[str, Any]:
        """Release a reservation by ID (e.g., if bot cancels withdrawal)"""
        if not reservation_id:
            return {'success': False, 'error': 'reservation_id is required'}

        # Find the reservation
        for item_code, reservations in self.item_reservations.items():
            if reservation_id in reservations:
                bot_name, quantity = reservations.pop(reservation_id)
                self.logger.info(f"Released reservation {reservation_id}: {quantity}x {item_code} for {bot_name}")

                # Clean up empty reservation dicts
                if not reservations:
                    del self.item_reservations[item_code]

                return {
                    'success': True,
                    'item_code': item_code,
                    'quantity': quantity,
                    'bot_name': bot_name
                }

        return {
            'success': False,
            'error': f'Reservation {reservation_id} not found'
        }

    async def _handle_update_after_withdraw(self, reservation_id: str, actual_quantity: int) -> Dict[str, Any]:
        """Update bank state after successful withdrawal

        Args:
            reservation_id: The reservation ID
            actual_quantity: The actual quantity withdrawn (may differ from reserved if API limits applied)
        """
        if not reservation_id:
            return {'success': False, 'error': 'reservation_id is required'}

        # Find and remove the reservation
        item_code = None
        reserved_quantity = None
        bot_name = None

        for code, reservations in self.item_reservations.items():
            if reservation_id in reservations:
                item_code = code
                bot_name, reserved_quantity = reservations.pop(reservation_id)
                break

        if not item_code:
            return {'success': False, 'error': f'Reservation {reservation_id} not found'}

        # Clean up empty reservation dicts
        if not self.item_reservations[item_code]:
            del self.item_reservations[item_code]

        # Update item quantity with ACTUAL withdrawn amount
        current_qty = self.items.get(item_code, 0)
        new_qty = max(0, current_qty - actual_quantity)

        if new_qty == 0:
            self.items.pop(item_code, None)
        else:
            self.items[item_code] = new_qty

        log_msg = f"Withdrew {actual_quantity}x {item_code} for {bot_name} (reserved: {reserved_quantity}). New bank qty: {new_qty}"
        if actual_quantity != reserved_quantity:
            log_msg += f" [WARNING: Actual differs from reserved]"
        self.logger.info(log_msg)

        return {
            'success': True,
            'item_code': item_code,
            'reserved_quantity': reserved_quantity,
            'actual_quantity': actual_quantity,
            'new_quantity': new_qty
        }

    async def _handle_update_after_deposit(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Update bank state after successful deposit"""
        deposited = []

        for item in items:
            item_code = item['code']
            quantity = item['quantity']

            current_qty = self.items.get(item_code, 0)
            new_qty = current_qty + quantity
            self.items[item_code] = new_qty

            deposited.append({'code': item_code, 'quantity': quantity, 'new_total': new_qty})
            self.logger.info(f"Deposited {quantity}x {item_code}. New bank qty: {new_qty}")

        return {'success': True, 'deposited': deposited}

    # ===== Gold operations =====

    async def _handle_check_gold(self, quantity: int) -> Dict[str, Any]:
        """Check if gold is available (considering reservations)"""
        total_gold = self.bank.gold if self.bank else 0

        # Calculate reserved gold
        reserved = sum(qty for _, qty in self.gold_reservations.values())

        available = total_gold - reserved
        is_available = available >= quantity

        return {
            'available': is_available,
            'total_in_bank': total_gold,
            'reserved': reserved,
            'free': available,
            'requested': quantity
        }

    async def _handle_reserve_gold(self, quantity: int, bot_name: str) -> Dict[str, Any]:
        """Reserve gold for withdrawal - returns reservation_id"""
        if not bot_name:
            return {'success': False, 'error': 'bot_name is required'}

        # Check availability
        check_result = await self._handle_check_gold(quantity)

        if not check_result['available']:
            return {
                'success': False,
                'error': f'Insufficient gold: requested {quantity}, available {check_result["free"]}',
                'details': check_result
            }

        # Create unique reservation ID
        reservation_id = str(uuid.uuid4())

        # Create reservation
        self.gold_reservations[reservation_id] = (bot_name, quantity)
        self.logger.info(f"Reserved {quantity} gold for {bot_name} (reservation_id: {reservation_id})")

        return {
            'success': True,
            'reservation_id': reservation_id,
            'reserved': quantity,
            'bot_name': bot_name
        }

    async def _handle_release_gold_reservation(self, reservation_id: str) -> Dict[str, Any]:
        """Release a gold reservation by ID"""
        if not reservation_id:
            return {'success': False, 'error': 'reservation_id is required'}

        if reservation_id in self.gold_reservations:
            bot_name, quantity = self.gold_reservations.pop(reservation_id)
            self.logger.info(f"Released gold reservation {reservation_id}: {quantity} for {bot_name}")

            return {
                'success': True,
                'quantity': quantity,
                'bot_name': bot_name
            }

        return {
            'success': False,
            'error': f'Gold reservation {reservation_id} not found'
        }

    async def _handle_update_after_gold_withdraw(self, reservation_id: str, actual_quantity: int) -> Dict[str, Any]:
        """Update bank state after successful gold withdrawal

        Args:
            reservation_id: The reservation ID
            actual_quantity: The actual quantity withdrawn (may differ from reserved if API limits applied)
        """
        if not reservation_id:
            return {'success': False, 'error': 'reservation_id is required'}

        if reservation_id not in self.gold_reservations:
            return {'success': False, 'error': f'Gold reservation {reservation_id} not found'}

        # Remove reservation
        bot_name, reserved_quantity = self.gold_reservations.pop(reservation_id)

        # Update gold with ACTUAL withdrawn amount
        if self.bank:
            self.bank.gold = max(0, self.bank.gold - actual_quantity)

        log_msg = f"Withdrew {actual_quantity} gold for {bot_name} (reserved: {reserved_quantity}). New bank gold: {self.bank.gold if self.bank else 0}"
        if actual_quantity != reserved_quantity:
            log_msg += f" [WARNING: Actual differs from reserved]"
        self.logger.info(log_msg)

        return {
            'success': True,
            'reserved_quantity': reserved_quantity,
            'actual_quantity': actual_quantity,
            'new_quantity': self.bank.gold if self.bank else 0
        }

    async def _handle_update_after_gold_deposit(self, quantity: int) -> Dict[str, Any]:
        """Update bank state after successful gold deposit"""
        if not quantity or quantity <= 0:
            return {'success': False, 'error': 'Invalid quantity'}

        if self.bank:
            self.bank.gold += quantity

        self.logger.info(f"Deposited {quantity} gold. New bank gold: {self.bank.gold if self.bank else 0}")

        return {
            'success': True,
            'deposited': quantity,
            'new_total': self.bank.gold if self.bank else 0
        }

    # ===== Utility methods =====

    def get_available_quantity(self, item_code: str) -> int:
        """Get available quantity of an item (total - reserved)"""
        total = self.items.get(item_code, 0)
        reserved = sum(qty for _, qty in self.item_reservations.get(item_code, {}).values())
        return max(0, total - reserved)

    def get_available_gold(self) -> int:
        """Get available gold (total - reserved)"""
        total = self.bank.gold if self.bank else 0
        reserved = sum(qty for _, qty in self.gold_reservations.values())
        return max(0, total - reserved)
