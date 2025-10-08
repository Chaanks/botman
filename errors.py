class ArtifactsError(Exception):
    """Base exception for all Artifacts-related errors"""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class TaskError(Exception):
    """Base exception for task execution errors"""

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


# ===== Custom Application Error Codes =====

CODE_RESOURCE_NOT_FOUND = 1000
CODE_MONSTER_NOT_FOUND = 1001
CODE_WORKSHOP_NOT_FOUND = 1002
CODE_ITEM_NOT_FOUND = 1003
CODE_INVALID_TASK_STATE = 1004


# ===== Specific Exception Classes =====


class CharacterInCooldownError(ArtifactsError):
    """Character is in cooldown"""

    def __init__(self, message: str = "Character is in cooldown"):
        super().__init__(CODE_CHARACTER_IN_COOLDOWN, message)


class InventoryFullError(ArtifactsError):
    """Character inventory is full"""

    def __init__(self, message: str = "Inventory is full"):
        super().__init__(CODE_CHARACTER_INVENTORY_FULL, message)


class InsufficientResourcesError(ArtifactsError):
    """Not enough resources/items"""

    def __init__(self, message: str = "Insufficient resources"):
        super().__init__(CODE_MISSING_ITEM, message)


class MapNotFoundError(ArtifactsError):
    """Map or location not found"""

    def __init__(self, message: str = "Map not found"):
        super().__init__(CODE_MAP_NOT_FOUND, message)


class ResourceNotFoundError(TaskError):
    """Resource gathering location not found"""

    def __init__(self, resource_code: str):
        self.resource_code = resource_code
        super().__init__(f"Cannot find gathering location for resource: {resource_code}")


class MonsterNotFoundError(TaskError):
    """Monster location not found"""

    def __init__(self, monster_code: str):
        self.monster_code = monster_code
        super().__init__(f"Cannot find location for monster: {monster_code}")


class WorkshopNotFoundError(TaskError):
    """Workshop location not found"""

    def __init__(self, skill: str):
        self.skill = skill
        super().__init__(f"Cannot find workshop for skill: {skill}")


def error_from_response(code: int, message: str) -> ArtifactsError:
    """Create specific exception from API error response"""
    # Map to specific exceptions
    if code == CODE_CHARACTER_IN_COOLDOWN:
        return CharacterInCooldownError(message)
    elif code == CODE_CHARACTER_INVENTORY_FULL:
        return InventoryFullError(message)
    elif code == CODE_MISSING_ITEM:
        return InsufficientResourcesError(message)
    elif code == CODE_MAP_NOT_FOUND:
        return MapNotFoundError(message)
    else:
        return ArtifactsError(code, message)
