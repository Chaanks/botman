"""API client and models for Artifacts MMO."""

from botman.core.api.client import ArtifactsClient
from botman.core.api.models import (
    # Enums
    CharacterRole,
    ItemSlot,
    Skill,
    # Basic types
    Position,
    SkillLevel,
    InventoryItem,
    # Character
    CharacterStats,
    CharacterSkills,
    CharacterEquipment,
    CharacterCooldown,
    ActiveEffect,
    Character,
    # Action results
    Cooldown,
    ActionResult,
    ItemDrop,
    CharacterFightResult,
    Fight,
    FightResult,
    SkillGain,
    GatherResult,
    CraftResult,
    RecycleResult,
    EquipmentChange,
    EquipResult,
    MoveResult,
    # Bank
    Bank,
    BankItem,
    BankResult,
    BankItemTransaction,
    # Trade
    Trade,
    TradeResult,
    GEOrder,
    GETransaction,
    GEResult,
    # Tasks
    Task,
    TaskReward,
    TaskResult,
    TaskCompleteResult,
    # Account
    Account,
    CharacterInfo,
    CharacterList,
    # Logs
    LogEntry,
    LogPage,
    # Achievements
    Achievement,
    AccountAchievement,
    AchievementPage,
    AccountAchievementPage,
    # Badges
    Badge,
    BadgePage,
    # Public account
    PublicAccount,
    # Effects
    Effect,
    EffectPage,
    # Events
    EventContent,
    Event,
    ActiveEvent,
    EventPage,
    ActiveEventPage,
    # Items
    CraftRequirement,
    CraftInfo,
    ItemEffect,
    Item,
    ItemPage,
    # Maps
    MapContent,
    MapInteractions,
    Map,
    MapPage,
    # Monsters
    MonsterDrop,
    Monster,
    MonsterPage,
    # NPCs
    NPC,
    NPCItem,
    NPCPage,
    NPCItemPage,
    # Resources
    ResourceDrop,
    Resource,
    ResourcePage,
    # Leaderboards
    CharacterLeaderboard,
    AccountLeaderboard,
    CharacterLeaderboardPage,
    AccountLeaderboardPage,
    # Active characters
    ActiveCharacter,
    ActiveCharacterPage,
    # GE History
    GEOrderHistory,
    GEOrderHistoryPage,
    GEOrderPage,
    # Tasks (full)
    TaskFull,
    TaskFullPage,
    TaskRewardDrop,
    TaskRewardDropPage,
    # Simulation
    FakeCharacter,
    CombatResult,
    CombatSimulation,
    # Token
    TokenResponse,
    # Server
    Announcement,
    ServerStatus,
    # Errors
    ApiError,
)

__all__ = [
    "ArtifactsClient",
    # Enums
    "CharacterRole",
    "ItemSlot",
    "Skill",
    # Basic types
    "Position",
    "SkillLevel",
    "InventoryItem",
    # Character
    "CharacterStats",
    "CharacterSkills",
    "CharacterEquipment",
    "CharacterCooldown",
    "ActiveEffect",
    "Character",
    # Action results
    "Cooldown",
    "ActionResult",
    "ItemDrop",
    "CharacterFightResult",
    "Fight",
    "FightResult",
    "SkillGain",
    "GatherResult",
    "CraftResult",
    "RecycleResult",
    "EquipmentChange",
    "EquipResult",
    "MoveResult",
    # Bank
    "Bank",
    "BankItem",
    "BankResult",
    "BankItemTransaction",
    # Trade
    "Trade",
    "TradeResult",
    "GEOrder",
    "GETransaction",
    "GEResult",
    # Tasks
    "Task",
    "TaskReward",
    "TaskResult",
    "TaskCompleteResult",
    # Account
    "Account",
    "CharacterInfo",
    "CharacterList",
    # Logs
    "LogEntry",
    "LogPage",
    # Achievements
    "Achievement",
    "AccountAchievement",
    "AchievementPage",
    "AccountAchievementPage",
    # Badges
    "Badge",
    "BadgePage",
    # Public account
    "PublicAccount",
    # Effects
    "Effect",
    "EffectPage",
    # Events
    "EventContent",
    "Event",
    "ActiveEvent",
    "EventPage",
    "ActiveEventPage",
    # Items
    "CraftRequirement",
    "CraftInfo",
    "ItemEffect",
    "Item",
    "ItemPage",
    # Maps
    "MapContent",
    "MapInteractions",
    "Map",
    "MapPage",
    # Monsters
    "MonsterDrop",
    "Monster",
    "MonsterPage",
    # NPCs
    "NPC",
    "NPCItem",
    "NPCPage",
    "NPCItemPage",
    # Resources
    "ResourceDrop",
    "Resource",
    "ResourcePage",
    # Leaderboards
    "CharacterLeaderboard",
    "AccountLeaderboard",
    "CharacterLeaderboardPage",
    "AccountLeaderboardPage",
    # Active characters
    "ActiveCharacter",
    "ActiveCharacterPage",
    # GE History
    "GEOrderHistory",
    "GEOrderHistoryPage",
    "GEOrderPage",
    # Tasks (full)
    "TaskFull",
    "TaskFullPage",
    "TaskRewardDrop",
    "TaskRewardDropPage",
    # Simulation
    "FakeCharacter",
    "CombatResult",
    "CombatSimulation",
    # Token
    "TokenResponse",
    # Server
    "Announcement",
    "ServerStatus",
    # Errors
    "ApiError",
]
