"""
Protocol definition for bank service.

This protocol defines the interface for bank operations available to tasks,
allowing them to interact with the bank without depending on the specific
BankActor implementation.
"""

from typing import Protocol, Any


class BankService(Protocol):
    """
    Protocol for bank operations available to tasks.

    This allows tasks to interact with the bank without depending
    on the specific BankActor implementation.
    """

    async def ask(self, message: Any) -> Any:
        """
        Send a request message to the bank and wait for response.

        Args:
            message: Typed message object (e.g., ReserveItemMessage)

        Returns:
            Typed response object (e.g., ReserveItemResponse)
        """
        ...

    async def tell(self, message: Any) -> None:
        """
        Send a fire-and-forget message to the bank.

        Args:
            message: Typed message object
        """
        ...
