"""
Service protocols for dependency injection into tasks.

These protocols define interfaces for shared services (Bank, etc.)
without coupling to specific Actor implementations.
"""

from typing import Protocol, Dict, Any


class BankService(Protocol):
    """
    Protocol for bank operations available to tasks.

    This allows tasks to interact with the bank without depending
    on the specific BankActor implementation.
    """

    async def ask(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a request message to the bank and wait for response.

        Args:
            message: Message dict with 'type' and operation-specific fields

        Returns:
            Response dict with operation results
        """
        ...

    async def tell(self, message: Dict[str, Any]) -> None:
        """
        Send a fire-and-forget message to the bank.

        Args:
            message: Message dict with 'type' and operation-specific fields
        """
        ...

