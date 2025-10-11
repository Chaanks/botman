class BotmanError(Exception):
    """Base exception"""
    pass


class APIError(BotmanError):
    """
    Base exception for all errors originating from the Artifacts API.
    """
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class FatalError(APIError):
    """
    An error that should stop the bot.
    """
    pass


class RecoverableError(APIError):
    """
    An error that pauses the current task and may require a new,
    corrective task to be run before the original can resume.
    """
    pass


class RetriableError(APIError):
    """
    An error that can be resolved by waiting and retrying the same action.
    """
    pass


# ===== API Error Codes =====

# General
CODE_INVALID_PAYLOAD = 422
CODE_TOO_MANY_REQUESTS = 429
CODE_NOT_FOUND = 404
CODE_FATAL_ERROR = 500

# Email token error codes
CODE_INVALID_EMAIL_RESET_TOKEN = 560
CODE_EXPIRED_EMAIL_RESET_TOKEN = 561
CODE_USED_EMAIL_RESET_TOKEN = 562

# Account Error Codes
CODE_TOKEN_INVALID = 452
CODE_TOKEN_EXPIRED = 453
CODE_TOKEN_MISSING = 454
CODE_TOKEN_GENERATION_FAIL = 455
CODE_USERNAME_ALREADY_USED = 456
CODE_EMAIL_ALREADY_USED = 457
CODE_SAME_PASSWORD = 458
CODE_CURRENT_PASSWORD_INVALID = 459
CODE_ACCOUNT_NOT_MEMBER = 451
CODE_ACCOUNT_SKIN_NOT_OWNED = 550

# Character Error Codes
CODE_CHARACTER_NOT_ENOUGH_HP = 483
CODE_CHARACTER_MAXIMUM_UTILITIES_EQUIPPED = 484
CODE_CHARACTER_ITEM_ALREADY_EQUIPPED = 485
CODE_CHARACTER_LOCKED = 486
CODE_CHARACTER_NOT_THIS_TASK = 474
CODE_CHARACTER_TOO_MANY_ITEMS_TASK = 475
CODE_CHARACTER_NO_TASK = 487
CODE_CHARACTER_TASK_NOT_COMPLETED = 488
CODE_CHARACTER_ALREADY_TASK = 489
CODE_CHARACTER_ALREADY_MAP = 490
CODE_CHARACTER_SLOT_EQUIPMENT_ERROR = 491
CODE_CHARACTER_GOLD_INSUFFICIENT = 492
CODE_CHARACTER_NOT_SKILL_LEVEL_REQUIRED = 493
CODE_CHARACTER_NAME_ALREADY_USED = 494
CODE_MAX_CHARACTERS_REACHED = 495
CODE_CHARACTER_CONDITION_NOT_MET = 496
CODE_CHARACTER_INVENTORY_FULL = 497
CODE_CHARACTER_NOT_FOUND = 498
CODE_CHARACTER_IN_COOLDOWN = 499

# Item Error Codes
CODE_ITEM_INVALID_EQUIPMENT = 472
CODE_ITEM_RECYCLING_INVALID_ITEM = 473
CODE_ITEM_INVALID_CONSUMABLE = 476
CODE_MISSING_ITEM = 478

# Grand Exchange Error Codes
CODE_GE_MAX_QUANTITY = 479
CODE_GE_NOT_IN_STOCK = 480
CODE_GE_NOT_THE_PRICE = 482
CODE_GE_TRANSACTION_IN_PROGRESS = 436
CODE_GE_NO_ORDERS = 431
CODE_GE_MAX_ORDERS = 433
CODE_GE_TOO_MANY_ITEMS = 434
CODE_GE_SAME_ACCOUNT = 435
CODE_GE_INVALID_ITEM = 437
CODE_GE_NOT_YOUR_ORDER = 438

# Bank Error Codes
CODE_BANK_INSUFFICIENT_GOLD = 460
CODE_BANK_TRANSACTION_IN_PROGRESS = 461
CODE_BANK_FULL = 462

# Maps Error Codes
CODE_MAP_NO_PATH_FOUND = 595
CODE_MAP_BLOCKED = 596
CODE_MAP_NOT_FOUND = 597
CODE_MAP_CONTENT_NOT_FOUND = 598

# NPC Error Codes
CODE_NPC_NOT_FOR_SALE = 441
CODE_NPC_NOT_FOR_BUY = 442

# Event Error Codes
CODE_EVENT_INSUFFICIENT_TOKENS = 563
CODE_EVENT_NOT_FOUND = 564

# Custom Application Error Codes
CODE_RESOURCE_NOT_FOUND = 1000
CODE_MONSTER_NOT_FOUND = 1001
CODE_WORKSHOP_NOT_FOUND = 1002
CODE_ITEM_NOT_FOUND = 1003
CODE_INVALID_TASK_STATE = 1004


# Error Code Categorization 

# Errors that should stop the bot
FATAL_ERROR_CODES = {
    CODE_TOKEN_INVALID,
    CODE_TOKEN_EXPIRED,
    CODE_TOKEN_MISSING,
    CODE_ACCOUNT_NOT_MEMBER,

    CODE_RESOURCE_NOT_FOUND,
    CODE_MONSTER_NOT_FOUND,
    CODE_WORKSHOP_NOT_FOUND,
    CODE_ITEM_NOT_FOUND,
    CODE_INVALID_TASK_STATE,
}

# Errors that need corrective action
RECOVERABLE_ERROR_CODES = {
    CODE_CHARACTER_INVENTORY_FULL,
    CODE_BANK_FULL,
}

# Errors that just need time
RETRIABLE_ERROR_CODES = {
    CODE_CHARACTER_IN_COOLDOWN,
    CODE_GE_TRANSACTION_IN_PROGRESS,
    CODE_BANK_TRANSACTION_IN_PROGRESS,
}


def error_from_response(code: int, message: str) -> APIError:
    """
    Create an exception from an API error response.
    
    Returns the appropriate exception type based on the error code's behavior:
    - FatalError: Stop the bot
    - RecoverableError: Pause task and run recovery
    - RetriableError: Wait and retry
    - APIError: Log and fail task
    
    Args:
        code: The error code from the API
        message: The error message from the API
        
    Returns:
        An exception instance with the appropriate behavior type
        
    Example:
        >>> error = error_from_response(497, "Inventory is full")
        >>> isinstance(error, RecoverableError)
        True
        >>> error.code
        497
    """
    if code in FATAL_ERROR_CODES:
        return FatalError(code, message)
    elif code in RECOVERABLE_ERROR_CODES:
        return RecoverableError(code, message)
    elif code in RETRIABLE_ERROR_CODES:
        return RetriableError(code, message)
    else:
        return APIError(code, message)


def get_error_behavior(code: int) -> str:
    """
    Get the behavior type for an error code.
    
    Returns: "fatal", "recoverable", "retriable", or "normal"
    """
    if code in FATAL_ERROR_CODES:
        return "fatal"
    elif code in RECOVERABLE_ERROR_CODES:
        return "recoverable"
    elif code in RETRIABLE_ERROR_CODES:
        return "retriable"
    else:
        return "normal"