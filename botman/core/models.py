from pydantic import BaseModel, computed_field, field_validator, model_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ===== Enums =====
class ItemSlot(str, Enum):
    WEAPON = "weapon"
    SHIELD = "shield"
    HELMET = "helmet"
    BODY_ARMOR = "body_armor"
    LEG_ARMOR = "leg_armor"
    BOOTS = "boots"
    RING1 = "ring1"
    RING2 = "ring2"
    AMULET = "amulet"
    ARTIFACT1 = "artifact1"
    ARTIFACT2 = "artifact2"
    ARTIFACT3 = "artifact3"


class Skill(str, Enum):
    MINING = "mining"
    WOODCUTTING = "woodcutting"
    FISHING = "fishing"
    WEAPONCRAFTING = "weaponcrafting"
    GEARCRAFTING = "gearcrafting"
    JEWELRYCRAFTING = "jewelrycrafting"
    COOKING = "cooking"
    ALCHEMY = "alchemy"


# ===== Basic Types =====
class Position(BaseModel):
    x: int
    y: int

    def distance_to(self, other: "Position") -> int:
        """Calculate Manhattan distance to another position"""
        return abs(self.x - other.x) + abs(self.y - other.y)

    def __iter__(self):
        """Allow unpacking: x, y = position"""
        return iter((self.x, self.y))

    def __str__(self) -> str:
        return f"({self.x}, {self.y})"


class SkillLevel(BaseModel):
    level: int
    xp: int
    max_xp: int

    @computed_field
    def progress(self) -> float:
        """Progress to next level (0.0 to 1.0)"""
        return self.xp / self.max_xp if self.max_xp > 0 else 0.0


class InventoryItem(BaseModel):
    slot: int
    code: str
    quantity: int


# ===== Character =====
class CharacterStats(BaseModel):
    """Character health and combat statistics"""

    hp: int
    max_hp: int
    haste: int
    critical_strike: int
    wisdom: int
    prospecting: int
    initiative: int
    threat: int
    attack_fire: int
    attack_earth: int
    attack_water: int
    attack_air: int
    dmg: int  # Overall damage %
    dmg_fire: int
    dmg_earth: int
    dmg_water: int
    dmg_air: int
    res_fire: int
    res_earth: int
    res_water: int
    res_air: int

    def total_attack(self) -> int:
        """Sum of all attack elements"""
        return (
            self.attack_fire + self.attack_earth + self.attack_water + self.attack_air
        )

    def total_damage(self) -> int:
        """Sum of all damage elements"""
        return self.dmg_fire + self.dmg_earth + self.dmg_water + self.dmg_air

    def total_resistance(self) -> int:
        """Sum of all resistance elements"""
        return self.res_fire + self.res_earth + self.res_water + self.res_air


class CharacterSkills(BaseModel):
    """Character skill levels and experience"""

    mining: SkillLevel
    woodcutting: SkillLevel
    fishing: SkillLevel
    weaponcrafting: SkillLevel
    gearcrafting: SkillLevel
    jewelrycrafting: SkillLevel
    cooking: SkillLevel
    alchemy: SkillLevel


class CharacterEquipment(BaseModel):
    """Character equipped items"""

    weapon_slot: Optional[str] = None
    rune_slot: Optional[str] = None
    shield_slot: Optional[str] = None
    helmet_slot: Optional[str] = None
    body_armor_slot: Optional[str] = None
    leg_armor_slot: Optional[str] = None
    boots_slot: Optional[str] = None
    ring1_slot: Optional[str] = None
    ring2_slot: Optional[str] = None
    amulet_slot: Optional[str] = None
    artifact1_slot: Optional[str] = None
    artifact2_slot: Optional[str] = None
    artifact3_slot: Optional[str] = None
    utility1_slot: Optional[str] = None
    utility1_slot_quantity: int = 0
    utility2_slot: Optional[str] = None
    utility2_slot_quantity: int = 0
    bag_slot: Optional[str] = None


class CharacterCooldown(BaseModel):
    """Character cooldown information from API"""

    cooldown: int = 0
    cooldown_expiration: Optional[datetime] = None

    @field_validator("cooldown_expiration", mode="before")
    @classmethod
    def parse_cooldown(cls, v):
        if v is None:
            return None
        return datetime.fromisoformat(v.replace("Z", "+00:00"))

    def __str__(self):
        expiration = (
            self.cooldown_expiration.isoformat() if self.cooldown_expiration else None
        )
        return f"CharacterCooldown(cooldown={self.cooldown}, cooldown_expiration={expiration})"


class ActiveEffect(BaseModel):
    """Active effect on a character"""

    name: str
    code: str
    value: int
    duration: int  # Duration in seconds
    expiration: datetime

    @field_validator("expiration", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


# ===== Character State =====
class Character(BaseModel):
    """Complete character state"""

    # Core
    name: str
    account: str
    skin: str
    level: int
    xp: int
    max_xp: int
    gold: int
    speed: int

    # Position
    position: Position
    layer: str  # "overworld", "underground", or "interior"
    map_id: int

    # Composed models
    stats: CharacterStats
    skills: CharacterSkills
    equipment: CharacterEquipment
    cooldown_info: CharacterCooldown

    # Effects
    effects: List[ActiveEffect] = []

    # Task
    task: Optional[str] = None
    task_type: Optional[str] = None
    task_progress: Optional[int] = None
    task_total: Optional[int] = None

    # Inventory
    inventory: List[InventoryItem]
    inventory_max_items: int

    # ===== Factory Method =====
    @classmethod
    def from_api_data(cls, data: dict) -> "Character":
        """Create Character from flat API response"""
        return cls(
            # Core fields
            name=data["name"],
            account=data["account"],
            skin=data["skin"],
            level=data["level"],
            xp=data["xp"],
            max_xp=data["max_xp"],
            gold=data["gold"],
            speed=data["speed"],
            # Position
            position=Position(x=data["x"], y=data["y"]),
            layer=data["layer"],
            map_id=data["map_id"],
            # Stats
            stats=CharacterStats(
                hp=data["hp"],
                max_hp=data["max_hp"],
                haste=data["haste"],
                critical_strike=data["critical_strike"],
                wisdom=data["wisdom"],
                prospecting=data["prospecting"],
                initiative=data["initiative"],
                threat=data["threat"],
                attack_fire=data["attack_fire"],
                attack_earth=data["attack_earth"],
                attack_water=data["attack_water"],
                attack_air=data["attack_air"],
                dmg=data["dmg"],
                dmg_fire=data["dmg_fire"],
                dmg_earth=data["dmg_earth"],
                dmg_water=data["dmg_water"],
                dmg_air=data["dmg_air"],
                res_fire=data["res_fire"],
                res_earth=data["res_earth"],
                res_water=data["res_water"],
                res_air=data["res_air"],
            ),
            # Skills
            skills=CharacterSkills(
                mining=SkillLevel(
                    level=data["mining_level"],
                    xp=data["mining_xp"],
                    max_xp=data["mining_max_xp"],
                ),
                woodcutting=SkillLevel(
                    level=data["woodcutting_level"],
                    xp=data["woodcutting_xp"],
                    max_xp=data["woodcutting_max_xp"],
                ),
                fishing=SkillLevel(
                    level=data["fishing_level"],
                    xp=data["fishing_xp"],
                    max_xp=data["fishing_max_xp"],
                ),
                weaponcrafting=SkillLevel(
                    level=data["weaponcrafting_level"],
                    xp=data["weaponcrafting_xp"],
                    max_xp=data["weaponcrafting_max_xp"],
                ),
                gearcrafting=SkillLevel(
                    level=data["gearcrafting_level"],
                    xp=data["gearcrafting_xp"],
                    max_xp=data["gearcrafting_max_xp"],
                ),
                jewelrycrafting=SkillLevel(
                    level=data["jewelrycrafting_level"],
                    xp=data["jewelrycrafting_xp"],
                    max_xp=data["jewelrycrafting_max_xp"],
                ),
                cooking=SkillLevel(
                    level=data["cooking_level"],
                    xp=data["cooking_xp"],
                    max_xp=data["cooking_max_xp"],
                ),
                alchemy=SkillLevel(
                    level=data["alchemy_level"],
                    xp=data["alchemy_xp"],
                    max_xp=data["alchemy_max_xp"],
                ),
            ),
            # Equipment
            equipment=CharacterEquipment(
                weapon_slot=data.get("weapon_slot"),
                rune_slot=data.get("rune_slot"),
                shield_slot=data.get("shield_slot"),
                helmet_slot=data.get("helmet_slot"),
                body_armor_slot=data.get("body_armor_slot"),
                leg_armor_slot=data.get("leg_armor_slot"),
                boots_slot=data.get("boots_slot"),
                ring1_slot=data.get("ring1_slot"),
                ring2_slot=data.get("ring2_slot"),
                amulet_slot=data.get("amulet_slot"),
                artifact1_slot=data.get("artifact1_slot"),
                artifact2_slot=data.get("artifact2_slot"),
                artifact3_slot=data.get("artifact3_slot"),
                utility1_slot=data.get("utility1_slot"),
                utility1_slot_quantity=data.get("utility1_slot_quantity", 0),
                utility2_slot=data.get("utility2_slot"),
                utility2_slot_quantity=data.get("utility2_slot_quantity", 0),
                bag_slot=data.get("bag_slot"),
            ),
            # Cooldown info
            cooldown_info=CharacterCooldown(
                cooldown=data.get("cooldown", 0),
                cooldown_expiration=data.get("cooldown_expiration"),
            ),
            # Effects
            effects=[ActiveEffect(**effect) for effect in data.get("effects", [])],
            # Task
            task=data.get("task"),
            task_type=data.get("task_type"),
            task_progress=data.get("task_progress"),
            task_total=data.get("task_total"),
            # Inventory
            inventory=[InventoryItem(**item) for item in data.get("inventory", [])],
            inventory_max_items=data["inventory_max_items"],
        )

    def ready_in(self) -> float:
        """Seconds until can act (0.0 if ready now)"""
        if not self.cooldown_info.cooldown_expiration:
            return 0.0
        now = datetime.now(self.cooldown_info.cooldown_expiration.tzinfo)
        return max(0.0, (self.cooldown_info.cooldown_expiration - now).total_seconds())

    def can_act(self) -> bool:
        """Check if character can perform actions"""
        return self.ready_in() == 0.0

    def has_item(self, code: str, quantity: int = 1) -> bool:
        """Check if has item in inventory"""
        total = sum(item.quantity for item in self.inventory if item.code == code)
        return total >= quantity

    def inventory_space(self) -> int:
        """Available inventory slots"""
        return self.inventory_max_items - len(self.inventory)

    def get_skill(self, skill: Skill) -> SkillLevel:
        """Get skill level by enum"""
        return getattr(self.skills, skill.value)

    def __str__(self) -> str:
        return f"{self.name} (Lvl {self.level}) @ {self.position} cooldown:{self.cooldown_info}"

    def __repr__(self) -> str:
        return f"<Character: {self.name} L{self.level} HP:{self.stats.hp}/{self.stats.max_hp} CD:{self.cooldown_info}>"


# ===== Action Results =====


class Cooldown(BaseModel):
    """Action cooldown information"""

    total_seconds: int
    started_at: datetime
    expiration: datetime
    reason: str

    @field_validator("started_at", "expiration", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v

    def __str__(self):
        return (
            f"Cooldown(reason='{self.reason}', duration={self.total_seconds}s, "
            f"expires={self.expiration.isoformat()})"
        )


class ActionResult(BaseModel):
    """Base result from any character action"""

    cooldown: Cooldown
    character: Character

    @model_validator(mode="before")
    @classmethod
    def transform_character(cls, data):
        """Transform flat character data from API to nested Character object"""
        if isinstance(data, dict) and "character" in data:
            char_data = data["character"]
            if isinstance(char_data, dict) and "position" not in char_data:
                # Flat API response - transform it
                data["character"] = Character.from_api_data(char_data)
        return data


class ItemDrop(BaseModel):
    """Item dropped from combat or gathering"""

    code: str
    quantity: int


class Fight(BaseModel):
    """Combat encounter details"""

    xp: int
    gold: int
    drops: List[ItemDrop]
    turns: int
    monster_blocked_hits: Dict[str, int]
    player_blocked_hits: Dict[str, int]
    logs: List[str]
    result: str  # "win" or "lose"


class FightResult(ActionResult):
    """Fight action outcome"""

    fight: Fight


class SkillGain(BaseModel):
    """Resources gained from skill action"""

    xp: int
    items: List[ItemDrop]


class GatherResult(ActionResult):
    """Gathering action outcome"""

    details: SkillGain


class CraftResult(ActionResult):
    """Crafting action outcome"""

    details: SkillGain


class RecycleResult(ActionResult):
    """Recycling action outcome"""

    details: SkillGain


class EquipmentChange(BaseModel):
    """Equipment slot modification"""

    slot: str
    item: Optional[str] = None
    quantity: int


class EquipResult(ActionResult):
    """Equipment change outcome"""

    details: EquipmentChange


class MoveResult(ActionResult):
    """Movement action outcome"""

    destination: "Map"  # Forward reference since Map is defined later
    path: Optional[List[List[int]]] = None


# ===== Bank =====


class Bank(BaseModel):
    """Bank account state"""

    slots: int
    expansions: int
    next_expansion_cost: int
    gold: int

    def available_slots(self, used_slots: int) -> int:
        """Calculate available bank slots"""
        return self.slots - used_slots


class BankItem(BaseModel):
    """Item in bank storage"""

    code: str
    quantity: int


class BankResult(ActionResult):
    """Bank transaction outcome for gold transactions"""

    bank: Bank


class BankItemTransaction(BaseModel):
    """Bank item deposit/withdraw transaction outcome"""

    cooldown: Cooldown
    items: List[ItemDrop]  # Items deposited/withdrawn
    bank: List[BankItem]  # Full bank inventory after transaction
    character: Character

    @model_validator(mode="before")
    @classmethod
    def transform_character(cls, data):
        """Transform flat character data from API to nested Character object"""
        if isinstance(data, dict) and "character" in data:
            char_data = data["character"]
            if isinstance(char_data, dict) and "position" not in char_data:
                # Flat API response - transform it
                data["character"] = Character.from_api_data(char_data)
        return data


# ===== Trade =====


class Trade(BaseModel):
    """Transaction details"""

    code: str
    quantity: int
    price: int
    total_price: int


class TradeResult(ActionResult):
    """NPC trade outcome"""

    transaction: Trade


class GEOrder(BaseModel):
    """Grand Exchange sell order"""

    id: str
    created_at: datetime
    code: str
    quantity: int
    price: int
    total_price: int

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class GETransaction(BaseModel):
    """Completed Grand Exchange sale"""

    id: str
    seller: str
    buyer: str
    code: str
    quantity: int
    price: int
    total_price: int
    sold_at: datetime

    @field_validator("sold_at", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class GEResult(ActionResult):
    """Grand Exchange transaction outcome"""

    transaction: Trade


# ===== Tasks =====


class Task(BaseModel):
    """Active task details"""

    code: str
    type: str  # "monsters" or "items"
    total: int
    progress: int = 0


class TaskReward(BaseModel):
    """Task completion reward"""

    code: str
    quantity: int


class TaskResult(ActionResult):
    """Task acceptance outcome"""

    task: Task


class TaskCompleteResult(ActionResult):
    """Task completion outcome"""

    rewards: List[TaskReward]


# ===== Account =====


class Account(BaseModel):
    """Player account details"""

    username: str
    email: Optional[str] = None
    member: bool
    member_expiration: Optional[datetime] = None
    status: str
    badges: List[str] = []
    skins: List[str] = []
    gems: int
    event_token: int
    achievements_points: int
    banned: bool = False
    ban_reason: Optional[str] = None

    @field_validator("member_expiration", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if v is None or isinstance(v, datetime):
            return v
        return datetime.fromisoformat(v.replace("Z", "+00:00"))


class CharacterInfo(BaseModel):
    """Character summary for lists"""

    name: str
    account: str
    skin: str
    level: int
    xp: int
    max_xp: int
    gold: int
    speed: int
    mining_level: int
    woodcutting_level: int
    fishing_level: int
    weaponcrafting_level: int
    gearcrafting_level: int
    jewelrycrafting_level: int
    cooking_level: int
    alchemy_level: int
    hp: int
    max_hp: int
    task: Optional[str] = None
    task_type: Optional[str] = None
    task_progress: Optional[int] = None
    task_total: Optional[int] = None
    inventory_max_items: int
    cooldown_expiration: Optional[datetime] = None

    @field_validator("cooldown_expiration", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if v is None or isinstance(v, datetime):
            return v
        return datetime.fromisoformat(v.replace("Z", "+00:00"))


class CharacterList(BaseModel):
    """Account character list"""

    characters: List[CharacterInfo]


# ===== Logs =====


class LogEntry(BaseModel):
    """Action history entry"""

    character: str
    account: str
    type: str
    description: str
    content: Dict[str, Any]
    cooldown: int
    cooldown_expiration: datetime
    created_at: datetime

    @field_validator("cooldown_expiration", "created_at", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class LogPage(BaseModel):
    """Paginated action logs"""

    data: List[LogEntry]
    total: int
    page: int
    size: int
    pages: int


# ===== Achievements =====


class Achievement(BaseModel):
    """Achievement details"""

    name: str
    code: str
    description: str
    points: int
    type: str
    target: Optional[int] = None
    total: Optional[int] = None


class AccountAchievement(BaseModel):
    """Account achievement with progress"""

    name: str
    code: str
    description: str
    points: int
    type: str
    target: Optional[int] = None
    total: Optional[int] = None
    progress: int
    completed_at: Optional[datetime] = None

    @field_validator("completed_at", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if v is None or isinstance(v, datetime):
            return v
        return datetime.fromisoformat(v.replace("Z", "+00:00"))


class AchievementPage(BaseModel):
    """Paginated achievements"""

    data: List[Achievement]
    total: int
    page: int
    size: int
    pages: int


class AccountAchievementPage(BaseModel):
    """Paginated account achievements"""

    data: List[AccountAchievement]
    total: int
    page: int
    size: int
    pages: int


# ===== Badges =====


class Badge(BaseModel):
    """Badge details"""

    code: str
    name: str
    description: str
    season: Optional[str] = None


class BadgePage(BaseModel):
    """Paginated badges"""

    data: List[Badge]
    total: int
    page: int
    size: int
    pages: int


# ===== Public Account =====


class PublicAccount(BaseModel):
    """Public account information"""

    username: str
    badges: List[str] = []
    achievements_points: int
    banned: bool = False
    ban_reason: Optional[str] = None


# ===== Effects =====


class Effect(BaseModel):
    """Effect details"""

    name: str
    code: str
    description: Optional[str] = None
    type: str
    value: int = 0
    duration: int = 0
    target: Optional[str] = None


class EffectPage(BaseModel):
    """Paginated effects"""

    data: List[Effect]
    total: int
    page: int
    size: int
    pages: int


# ===== Events =====


class EventContent(BaseModel):
    """Event content reference"""

    type: str
    code: str


class Event(BaseModel):
    """Event details"""

    name: str
    code: str
    map: EventContent
    previous_skin: str
    duration: int
    expiration: datetime
    rate: int

    @field_validator("expiration", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class ActiveEvent(BaseModel):
    """Active event details"""

    name: str
    code: str
    map: EventContent
    previous_skin: str
    duration: int
    expiration: datetime
    created_at: datetime

    @field_validator("expiration", "created_at", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class EventPage(BaseModel):
    """Paginated events"""

    data: List[Event]
    total: int
    page: int
    size: int
    pages: int


class ActiveEventPage(BaseModel):
    """Paginated active events"""

    data: List[ActiveEvent]
    total: int
    page: int
    size: int
    pages: int


# ===== Items =====


class CraftRequirement(BaseModel):
    """Crafting material requirement"""

    code: str
    quantity: int


class CraftInfo(BaseModel):
    """Crafting recipe information"""

    skill: Optional[str] = None
    level: Optional[int] = None
    requirements: List[CraftRequirement] = []
    quantity: int = 1  # How many items this recipe produces

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> Optional["CraftInfo"]:
        """Create CraftInfo from API dict format"""
        if not data:
            return None

        requirements = []
        if "items" in data:
            for item_data in data["items"]:
                requirements.append(CraftRequirement(
                    code=item_data["code"],
                    quantity=item_data["quantity"]
                ))

        return cls(
            skill=data.get("skill"),
            level=data.get("level"),
            requirements=requirements,
            quantity=data.get("quantity", 1)
        )


class ItemEffect(BaseModel):
    """Item effect"""

    name: Optional[str] = None
    value: int


class Item(BaseModel):
    """Item details"""

    name: str
    code: str
    level: int
    type: str
    subtype: Optional[str] = None
    description: Optional[str] = None
    effects: List[ItemEffect] = []
    craft: Optional[CraftInfo] = None
    tradeable: bool = True

    @model_validator(mode="before")
    @classmethod
    def transform_craft(cls, data):
        """Transform craft dict to CraftInfo"""
        if isinstance(data, dict) and "craft" in data:
            if isinstance(data["craft"], dict):
                data["craft"] = CraftInfo.from_dict(data["craft"])
        return data


class ItemPage(BaseModel):
    """Paginated items"""

    data: List[Item]
    total: int
    page: int
    size: int
    pages: int


# ===== Maps =====


class MapContent(BaseModel):
    """Map content details"""

    type: str
    code: str


class MapInteractions(BaseModel):
    """Map interactions (includes content)"""

    content: Optional[MapContent] = None
    transition: Optional[dict] = None


class Map(BaseModel):
    """Map details"""

    name: str
    skin: str
    x: int
    y: int
    layer: str
    interactions: Optional[MapInteractions] = None

    @property
    def content(self) -> Optional[MapContent]:
        """Convenience property to access interactions.content"""
        return self.interactions.content if self.interactions else None


class MapPage(BaseModel):
    """Paginated maps"""

    data: List[Map]
    total: int
    page: int
    size: int
    pages: int


# ===== Monsters =====


class MonsterDrop(BaseModel):
    """Monster drop information"""

    code: str
    rate: int
    min_quantity: int
    max_quantity: int


class Monster(BaseModel):
    """Monster details"""

    name: str
    code: str
    level: int
    hp: int
    attack_fire: int = 0
    attack_earth: int = 0
    attack_water: int = 0
    attack_air: int = 0
    res_fire: int = 0
    res_earth: int = 0
    res_water: int = 0
    res_air: int = 0
    min_gold: int = 0
    max_gold: int = 0
    drops: List[MonsterDrop] = []


class MonsterPage(BaseModel):
    """Paginated monsters"""

    data: List[Monster]
    total: int
    page: int
    size: int
    pages: int


# ===== NPCs =====


class NPC(BaseModel):
    """NPC details"""

    name: str
    code: str
    skin: str
    x: int
    y: int
    type: str


class NPCItem(BaseModel):
    """NPC item for trade"""

    code: str
    item_code: str
    item_name: str
    item_type: str
    item_subtype: Optional[str] = None
    npc_code: str
    npc_name: str
    price: int
    currency: str
    min_quantity: int = 1
    max_quantity: int = 1


class NPCPage(BaseModel):
    """Paginated NPCs"""

    data: List[NPC]
    total: int
    page: int
    size: int
    pages: int


class NPCItemPage(BaseModel):
    """Paginated NPC items"""

    data: List[NPCItem]
    total: int
    page: int
    size: int
    pages: int


# ===== Resources =====


class ResourceDrop(BaseModel):
    """Resource drop information"""

    code: str
    rate: int
    min_quantity: int
    max_quantity: int


class Resource(BaseModel):
    """Resource details"""

    name: str
    code: str
    skill: str
    level: int
    drops: List[ResourceDrop] = []


class ResourcePage(BaseModel):
    """Paginated resources"""

    data: List[Resource]
    total: int
    page: int
    size: int
    pages: int


# ===== Leaderboards =====


class CharacterLeaderboard(BaseModel):
    """Character leaderboard entry"""

    name: str
    account: str
    skin: str
    level: int
    xp: int
    gold: int
    achievements_points: int
    mining_level: int
    woodcutting_level: int
    fishing_level: int
    weaponcrafting_level: int
    gearcrafting_level: int
    jewelrycrafting_level: int
    cooking_level: int
    alchemy_level: int


class AccountLeaderboard(BaseModel):
    """Account leaderboard entry"""

    account: str
    achievements_points: int


class CharacterLeaderboardPage(BaseModel):
    """Paginated character leaderboard"""

    data: List[CharacterLeaderboard]
    total: int
    page: int
    size: int
    pages: int


class AccountLeaderboardPage(BaseModel):
    """Paginated account leaderboard"""

    data: List[AccountLeaderboard]
    total: int
    page: int
    size: int
    pages: int


# ===== Active Characters =====


class ActiveCharacter(BaseModel):
    """Currently active character summary"""

    name: str
    account: str
    skin: str
    level: int
    x: int
    y: int


class ActiveCharacterPage(BaseModel):
    """Paginated active characters"""

    data: List[ActiveCharacter]
    total: int
    page: int
    size: int
    pages: int


# ===== GE History (public) =====


class GEOrderHistory(BaseModel):
    """Grand Exchange order history entry"""

    id: str
    seller: str
    buyer: str
    code: str
    quantity: int
    price: int
    total_price: int
    sold_at: datetime

    @field_validator("sold_at", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class GEOrderHistoryPage(BaseModel):
    """Paginated GE order history"""

    data: List[GEOrderHistory]
    total: int
    page: int
    size: int
    pages: int


class GEOrderPage(BaseModel):
    """Paginated GE orders"""

    data: List[GEOrder]
    total: int
    page: int
    size: int
    pages: int


# ===== Tasks =====


class TaskFull(BaseModel):
    """Full task details"""

    code: str
    level: int
    type: str  # "monsters" or "items"
    min_quantity: int
    max_quantity: int
    skill: Optional[str] = None
    rewards: TaskReward


class TaskFullPage(BaseModel):
    """Paginated full tasks"""

    data: List[TaskFull]
    total: int
    page: int
    size: int
    pages: int


class TaskRewardDrop(BaseModel):
    """Task reward drop rate"""

    code: str
    rate: int
    min_quantity: int
    max_quantity: int


class TaskRewardDropPage(BaseModel):
    """Paginated task reward drops"""

    data: List[TaskRewardDrop]
    total: int
    page: int
    size: int
    pages: int


# ===== Simulation =====


class FakeCharacter(BaseModel):
    """Fake character for combat simulation"""

    level: int
    weapon_slot: Optional[str] = None
    rune_slot: Optional[str] = None
    shield_slot: Optional[str] = None
    helmet_slot: Optional[str] = None
    body_armor_slot: Optional[str] = None
    leg_armor_slot: Optional[str] = None
    boots_slot: Optional[str] = None
    ring1_slot: Optional[str] = None
    ring2_slot: Optional[str] = None
    amulet_slot: Optional[str] = None
    artifact1_slot: Optional[str] = None
    artifact2_slot: Optional[str] = None
    artifact3_slot: Optional[str] = None
    utility1_slot: Optional[str] = None
    utility1_slot_quantity: int = 1
    utility2_slot: Optional[str] = None
    utility2_slot_quantity: int = 1


class CombatResult(BaseModel):
    """Single combat result"""

    result: str  # "win" or "loss"
    turns: int
    logs: List[str]
    character_results: List[Dict[str, Any]]


class CombatSimulation(BaseModel):
    """Combat simulation results"""

    results: List[CombatResult]
    wins: int
    losses: int
    winrate: float


# ===== Token =====


class TokenResponse(BaseModel):
    """API token response"""

    token: str


# ===== Server =====


class Announcement(BaseModel):
    """Server announcement"""

    message: str
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class ServerStatus(BaseModel):
    """Game server state"""

    status: str
    version: str
    max_level: int
    characters_online: int
    server_time: datetime
    announcements: List[Announcement]
    last_wipe: Optional[datetime] = None
    next_wipe: Optional[datetime] = None

    @field_validator("server_time", "last_wipe", "next_wipe", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if v is None or isinstance(v, datetime):
            return v
        return datetime.fromisoformat(v.replace("Z", "+00:00"))


# ===== Errors =====


class ApiError(BaseModel):
    """API error information"""

    code: int
    message: str
    data: Optional[Dict[str, Any]] = None
