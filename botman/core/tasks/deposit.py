from dataclasses import dataclass
from typing import Optional, List, Dict

from botman.core.tasks.base import Task, TaskContext, TaskResult
from botman.core.errors import APIError, FatalError, RecoverableError, RetriableError


@dataclass
class DepositTask(Task):
    """
    Deposit items at the bank.
    1. Single item: Provide item_code and quantity
    2. Multiple items: Provide items list [{"code": "ash", "quantity": 10}, ...]
    3. Full inventory: Set deposit_all=True to deposit everything
    """
    item_code: Optional[str] = None
    quantity: Optional[int] = None
    items: Optional[List[Dict[str, any]]] = None
    deposit_all: bool = False

    def __post_init__(self):
        """Validate configuration"""
        modes = sum([
            bool(self.item_code and self.quantity),
            bool(self.items),
            self.deposit_all
        ])
        if modes == 0:
            raise ValueError("Must specify either item_code+quantity, items list, or deposit_all=True")
        if modes > 1:
            raise ValueError("Can only specify one deposit mode at a time")

    async def execute(self, context: TaskContext) -> TaskResult:
        name = context.character.name
        current_pos = context.character.position

        # Bank is typically at (4, 1) - we should look this up from world data
        # For now, hardcoding bank location
        BANK_X, BANK_Y = 4, 1

        # Step 1: Move to bank if not already there
        if (current_pos.x, current_pos.y) != (BANK_X, BANK_Y):
            try:
                result = await context.api.move(x=BANK_X, y=BANK_Y, name=name)
                return TaskResult(
                    completed=False,
                    character=result.character,
                    log_messages=[(f"Moving to bank at ({BANK_X}, {BANK_Y})", "INFO")],
                )
            except APIError as e:
                return TaskResult(
                    completed=False,
                    character=context.character,
                    error=e,
                    log_messages=[(f"Failed to move to bank: {e.message}", "ERROR")]
                )

        # Step 2: Prepare items list based on mode
        if self.deposit_all:
            items_to_deposit = [
                {"code": item.code, "quantity": item.quantity}
                for item in context.character.inventory
                if item.code  # Filter out empty slots
            ]
        elif self.items:
            items_to_deposit = self.items
        else:
            items_to_deposit = [{"code": self.item_code, "quantity": self.quantity}]

        # Check if we have anything to deposit
        if not items_to_deposit:
            return TaskResult(
                completed=True,
                character=context.character,
                log_messages=[("No items to deposit", "INFO")]
            )

        # Step 3: Deposit items
        try:
            # Debug: log what we're about to send
            import logging
            logger = logging.getLogger(f"botman.bot.{name}")
            logger.debug(f"Depositing items: {items_to_deposit}")

            result = await context.api.deposit_item(items=items_to_deposit, name=name)

            # Notify BankActor of deposit
            if context.bank:
                await context.bank.tell({
                    'type': 'update_after_deposit',
                    'items': items_to_deposit
                })

            # Build log message
            if len(items_to_deposit) == 1:
                item = items_to_deposit[0]
                log_msg = f"Deposited {item['code']} x{item['quantity']}"
            elif self.deposit_all:
                total_items = sum(item['quantity'] for item in items_to_deposit)
                log_msg = f"Deposited all inventory ({len(items_to_deposit)} types, {total_items} items)"
            else:
                total_items = sum(item['quantity'] for item in items_to_deposit)
                log_msg = f"Deposited {len(items_to_deposit)} item types ({total_items} items)"

            return TaskResult(
                completed=True,
                character=result.character,
                log_messages=[(log_msg, "INFO"), ("Deposit complete!", "INFO")]
            )
        except APIError as e:
            level = "WARNING" if isinstance(e, (RecoverableError, RetriableError)) else "ERROR"
            return TaskResult(
                completed=False,
                character=context.character,
                error=e,
                log_messages=[(f"Deposit failed: {e.message}", level)]
            )

    def progress(self) -> str:
        """Return progress indicator"""
        return "Depositing"

    def description(self) -> str:
        """Return human-readable task description"""
        if self.deposit_all:
            return "Deposit All Items"
        elif self.items:
            item_count = len(self.items)
            total_qty = sum(item.get("quantity", 0) for item in self.items)
            return f"Deposit {item_count} Item Types ({total_qty} total)"
        else:
            item_name = self.item_code.replace("_", " ").title()
            return f"Deposit {item_name} x{self.quantity}"
