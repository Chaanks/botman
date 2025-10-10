import httpx
import asyncio
import logging
from typing import Optional
from botman.core.models import *
from botman.core.errors import ArtifactsError, error_from_response

logger = logging.getLogger("botman.api")


class ArtifactsClient:
    BASE_URL = "https://api.artifactsmmo.com"

    def __init__(self, token: str):
        self.token = token
        self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-load the async client to ensure it's created in the right event loop"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=httpx.Timeout(
                    30.0, read=60.0
                ),  # Longer timeout for slow API responses
            )
        return self._client

    async def _request(
        self, method: str, endpoint: str, json: Optional[dict] = None
    ) -> dict:
        try:
            response = await self.client.request(
                method, f"{self.BASE_URL}{endpoint}", json=json
            )
            response.raise_for_status()
            return response.json()["data"]
        except httpx.HTTPStatusError as e:
            # Parse API error response
            try:
                error_data = e.response.json().get("error", {})
                code = error_data.get("code", e.response.status_code)
                message = error_data.get("message", str(e))
                raise error_from_response(code, message) from e
            except (ValueError, KeyError):
                # Fallback if response is not valid JSON
                raise ArtifactsError(e.response.status_code, str(e)) from e

    async def _request_paginated(
        self, method: str, endpoint: str, json: Optional[dict] = None
    ) -> dict:
        """Request that returns full response (for paginated endpoints)"""
        try:
            response = await self.client.request(
                method, f"{self.BASE_URL}{endpoint}", json=json
            )
            response.raise_for_status()
            return response.json()  # Return full response, not just ["data"]
        except httpx.HTTPStatusError as e:
            # Parse API error response
            try:
                error_data = e.response.json().get("error", {})
                code = error_data.get("code", e.response.status_code)
                message = error_data.get("message", str(e))
                raise error_from_response(code, message) from e
            except (ValueError, KeyError):
                # Fallback if response is not valid JSON
                raise ArtifactsError(e.response.status_code, str(e)) from e

    # ===== Server details =====
    async def get_server_status(self) -> ServerStatus:
        """Get server status"""
        data = await self._request("GET", "/")
        return ServerStatus.model_validate(data)

    # ===== My account =====

    async def get_bank(self) -> Bank:
        """Fetch bank details"""
        data = await self._request("GET", "/my/bank")
        return Bank.model_validate(data)

    async def get_bank_items(
        self, item_code: Optional[str] = None, page: int = 1, size: int = 50
    ) -> List[BankItem]:
        """Fetch items in bank"""
        params = [f"page={page}", f"size={size}"]
        if item_code:
            params.append(f"item_code={item_code}")
        endpoint = f"/my/bank/items?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return [BankItem.model_validate(item) for item in data]

    async def get_ge_orders(
        self, code: Optional[str] = None, page: int = 1, size: int = 50
    ) -> List[GEOrder]:
        """Fetch your Grand Exchange sell orders"""
        params = [f"page={page}", f"size={size}"]
        if code:
            params.append(f"code={code}")
        endpoint = f"/my/grandexchange/orders?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return [GEOrder.model_validate(order) for order in data]

    async def get_ge_history(
        self,
        order_id: Optional[str] = None,
        code: Optional[str] = None,
        page: int = 1,
        size: int = 50,
    ) -> List[GETransaction]:
        """Fetch Grand Exchange sales history (last 7 days)"""
        params = [f"page={page}", f"size={size}"]
        if order_id:
            params.append(f"id={order_id}")
        if code:
            params.append(f"code={code}")
        endpoint = f"/my/grandexchange/history?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return [GETransaction.model_validate(entry) for entry in data]

    async def get_account(self) -> Account:
        """Fetch account details"""
        data = await self._request("GET", "/my/details")
        return Account.model_validate(data)

    async def get_logs(
        self, name: str = None, page: int = 1, size: int = 50
    ) -> LogPage:
        """Get character action history"""
        endpoint = f"/my/logs/{name}?page={page}&size={size}"
        data = await self._request("GET", endpoint)
        return LogPage.model_validate(data)

    async def get_all_logs(self, page: int = 1, size: int = 50) -> LogPage:
        """Get logs for all characters (last 5000 actions)"""
        data = await self._request("GET", f"/my/logs?page={page}&size={size}")
        return LogPage.model_validate(data)

    async def change_password(self, current_password: str, new_password: str) -> dict:
        """Change account password (resets token)"""
        return await self._request(
            "POST",
            "/my/change_password",
            {"current_password": current_password, "new_password": new_password},
        )

    # ===== My characters =====
    async def move(self, x: int, y: int, name: str = None) -> MoveResult:
        """Move character to position (x, y)"""
        data = await self._request("POST", f"/my/{name}/action/move", {"x": x, "y": y})
        return MoveResult.model_validate(data)

    async def transition(self, name: str = None) -> ActionResult:
        """Execute a transition to another layer"""
        data = await self._request("POST", f"/my/{name}/action/transition")
        return ActionResult.model_validate(data)

    async def rest(self, name: str = None) -> ActionResult:
        """Rest to recover HP"""
        data = await self._request("POST", f"/my/{name}/action/rest")
        return ActionResult.model_validate(data)

    async def equip(
        self, item_code: str, slot: str, quantity: int = 1, name: str = None
    ) -> EquipResult:
        """Equip an item"""
        data = await self._request(
            "POST",
            f"/my/{name}/action/equip",
            {"code": item_code, "slot": slot, "quantity": quantity},
        )
        return EquipResult.model_validate(data)

    async def unequip(
        self, slot: str, quantity: int = 1, name: str = None
    ) -> EquipResult:
        """Unequip an item"""
        data = await self._request(
            "POST", f"/my/{name}/action/unequip", {"slot": slot, "quantity": quantity}
        )
        return EquipResult.model_validate(data)

    async def use_item(
        self, item_code: str, quantity: int = 1, name: str = None
    ) -> ActionResult:
        """Use a consumable item"""
        data = await self._request(
            "POST", f"/my/{name}/action/use", {"code": item_code, "quantity": quantity}
        )
        return ActionResult.model_validate(data)

    async def fight(
        self, participants: Optional[List[str]] = None, name: str = None
    ) -> FightResult:
        """Start a fight against a monster"""
        body = {"participants": participants or []}
        data = await self._request("POST", f"/my/{name}/action/fight", body)
        return FightResult.model_validate(data)

    async def gather(self, name: str = None) -> GatherResult:
        """Harvest a resource on the character's map"""
        data = await self._request("POST", f"/my/{name}/action/gathering")
        return GatherResult.model_validate(data)

    async def craft(
        self, item_code: str, quantity: int = 1, name: str = None
    ) -> CraftResult:
        """Craft an item at a workshop"""
        data = await self._request(
            "POST",
            f"/my/{name}/action/crafting",
            {"code": item_code, "quantity": quantity},
        )
        return CraftResult.model_validate(data)

    # ===== Bank actions =====

    async def deposit_gold(self, quantity: int, name: str = None) -> BankResult:
        """Deposit gold in bank"""
        data = await self._request(
            "POST", f"/my/{name}/action/bank/deposit/gold", {"quantity": quantity}
        )
        return BankResult.model_validate(data)

    async def deposit_item(self, items: List[dict], name: str = None) -> BankResult:
        """Deposit items in bank. items = [{"code": "item_code", "quantity": 1}, ...]"""
        data = await self._request(
            "POST", f"/my/{name}/action/bank/deposit/item", items
        )
        return BankResult.model_validate(data)

    async def withdraw_gold(self, quantity: int, name: str = None) -> BankResult:
        """Withdraw gold from bank"""
        data = await self._request(
            "POST", f"/my/{name}/action/bank/withdraw/gold", {"quantity": quantity}
        )
        return BankResult.model_validate(data)

    async def withdraw_item(self, items: List[dict], name: str = None) -> BankResult:
        """Withdraw items from bank. items = [{"code": "item_code", "quantity": 1}, ...]"""
        data = await self._request(
            "POST", f"/my/{name}/action/bank/withdraw/item", items
        )
        return BankResult.model_validate(data)

    async def buy_bank_expansion(self, name: str = None) -> BankResult:
        """Buy a 20 slots bank expansion"""
        data = await self._request("POST", f"/my/{name}/action/bank/buy_expansion")
        return BankResult.model_validate(data)

    # ===== NPC actions =====

    async def npc_buy(
        self, item_code: str, quantity: int = 1, name: str = None
    ) -> TradeResult:
        """Buy an item from NPC"""
        data = await self._request(
            "POST",
            f"/my/{name}/action/npc/buy",
            {"code": item_code, "quantity": quantity},
        )
        return TradeResult.model_validate(data)

    async def npc_sell(
        self, item_code: str, quantity: int = 1, name: str = None
    ) -> TradeResult:
        """Sell an item to NPC"""
        data = await self._request(
            "POST",
            f"/my/{name}/action/npc/sell",
            {"code": item_code, "quantity": quantity},
        )
        return TradeResult.model_validate(data)

    # ===== Grand Exchange actions =====

    async def ge_buy(self, order_id: str, quantity: int, name: str = None) -> GEResult:
        """Buy item from Grand Exchange"""
        data = await self._request(
            "POST",
            f"/my/{name}/action/grandexchange/buy",
            {"id": order_id, "quantity": quantity},
        )
        return GEResult.model_validate(data)

    async def ge_sell(
        self, item_code: str, quantity: int, price: int, name: str = None
    ) -> GEResult:
        """Create sell order at Grand Exchange (3% listing tax)"""
        data = await self._request(
            "POST",
            f"/my/{name}/action/grandexchange/sell",
            {"code": item_code, "quantity": quantity, "price": price},
        )
        return GEResult.model_validate(data)

    async def ge_cancel(self, order_id: str, name: str = None) -> GEResult:
        """Cancel a sell order at Grand Exchange"""
        data = await self._request(
            "POST", f"/my/{name}/action/grandexchange/cancel", {"id": order_id}
        )
        return GEResult.model_validate(data)

    # ===== Task actions =====

    async def task_accept(self, name: str = None) -> TaskResult:
        """Accept a new task"""
        data = await self._request("POST", f"/my/{name}/action/task/new")
        return TaskResult.model_validate(data)

    async def task_complete(self, name: str = None) -> TaskCompleteResult:
        """Complete current task"""
        data = await self._request("POST", f"/my/{name}/action/task/complete")
        return TaskCompleteResult.model_validate(data)

    async def task_trade(
        self, item_code: str, quantity: int, name: str = None
    ) -> ActionResult:
        """Trade items with Tasks Master"""
        data = await self._request(
            "POST",
            f"/my/{name}/action/task/trade",
            {"code": item_code, "quantity": quantity},
        )
        return ActionResult.model_validate(data)

    async def task_cancel(self, name: str = None) -> ActionResult:
        """Cancel task for 1 tasks coin"""
        data = await self._request("POST", f"/my/{name}/action/task/cancel")
        return ActionResult.model_validate(data)

    async def task_exchange(self, name: str = None) -> TaskCompleteResult:
        """Exchange 6 task coins for random reward"""
        data = await self._request("POST", f"/my/{name}/action/task/exchange")
        return TaskCompleteResult.model_validate(data)

    # ===== Other actions =====

    async def recycle(
        self, item_code: str, quantity: int = 1, name: str = None
    ) -> RecycleResult:
        """Recycle an item at workshop"""
        data = await self._request(
            "POST",
            f"/my/{name}/action/recycling",
            {"code": item_code, "quantity": quantity},
        )
        return RecycleResult.model_validate(data)

    async def give_gold(
        self, recipient: str, quantity: int, name: str = None
    ) -> ActionResult:
        """Give gold to another character on same map"""
        data = await self._request(
            "POST",
            f"/my/{name}/action/give/gold",
            {"name": recipient, "quantity": quantity},
        )
        return ActionResult.model_validate(data)

    async def give_item(
        self, recipient: str, items: List[dict], name: str = None
    ) -> ActionResult:
        """Give items to another character. items = [{"code": "item", "quantity": 1}, ...]"""
        data = await self._request(
            "POST", f"/my/{name}/action/give/item", {"name": recipient, "items": items}
        )
        return ActionResult.model_validate(data)

    async def delete_item(
        self, item_code: str, quantity: int, name: str = None
    ) -> ActionResult:
        """Delete item from inventory"""
        data = await self._request(
            "POST",
            f"/my/{name}/action/delete",
            {"code": item_code, "quantity": quantity},
        )
        return ActionResult.model_validate(data)

    async def change_skin(self, skin: str, name: str = None) -> ActionResult:
        """Change character skin"""
        data = await self._request(
            "POST", f"/my/{name}/action/change_skin", {"skin": skin}
        )
        return ActionResult.model_validate(data)

    async def get_my_characters(self) -> CharacterList:
        """List all characters in your account"""
        data = await self._request("GET", "/my/characters")
        return CharacterList.model_validate(data)

    # ===== Achievements =====
    async def get_achievements(
        self, achievement_type: Optional[str] = None, page: int = 1, size: int = 50
    ) -> AchievementPage:
        """Get all achievements"""
        params = [f"page={page}", f"size={size}"]
        if achievement_type:
            params.append(f"type={achievement_type}")
        endpoint = f"/achievements?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return AchievementPage.model_validate(data)

    async def get_achievement(self, code: str) -> Achievement:
        """Get achievement details by code"""
        data = await self._request("GET", f"/achievements/{code}")
        return Achievement.model_validate(data)

    async def get_account_achievements(
        self,
        account: str,
        achievement_type: Optional[str] = None,
        completed: Optional[bool] = None,
        page: int = 1,
        size: int = 50,
    ) -> AccountAchievementPage:
        """Get achievements for a specific account"""
        params = [f"page={page}", f"size={size}"]
        if achievement_type:
            params.append(f"type={achievement_type}")
        if completed is not None:
            params.append(f"completed={str(completed).lower()}")
        endpoint = f"/accounts/{account}/achievements?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return AccountAchievementPage.model_validate(data)

    async def get_public_account(self, account: str) -> PublicAccount:
        """Get public account details"""
        data = await self._request("GET", f"/accounts/{account}")
        return PublicAccount.model_validate(data)

    async def get_account_characters(self, account: str) -> CharacterList:
        """Get character list for an account"""
        data = await self._request("GET", f"/accounts/{account}/characters")
        return CharacterList.model_validate(data)

    # ===== Badges =====
    async def get_badges(self, page: int = 1, size: int = 50) -> BadgePage:
        """Get all badges"""
        data = await self._request("GET", f"/badges?page={page}&size={size}")
        return BadgePage.model_validate(data)

    async def get_badge(self, code: str) -> Badge:
        """Get badge details by code"""
        data = await self._request("GET", f"/badges/{code}")
        return Badge.model_validate(data)

    # ===== Characters
    async def create_character(self, name: str, skin: str = "men1") -> Character:
        """Create a new character"""
        data = await self._request(
            "POST", "/characters/create", {"name": name, "skin": skin}
        )
        return Character.from_api_data(data)

    async def delete_character(self, name: str) -> Character:
        """Delete a character"""
        data = await self._request("POST", "/characters/delete", {"name": name})
        return Character.from_api_data(data)

    async def get_active_characters(
        self, page: int = 1, size: int = 50
    ) -> ActiveCharacterPage:
        """Get list of currently active characters"""
        data = await self._request("GET", f"/characters/active?page={page}&size={size}")
        return ActiveCharacterPage.model_validate(data)

    async def get_character(self, name: str = None) -> Character:
        """Get character details"""
        data = await self._request("GET", f"/characters/{name}")
        return Character.from_api_data(data)

    # ===== Effects =====
    async def get_effects(self, page: int = 1, size: int = 50) -> EffectPage:
        """Get all effects"""
        data = await self._request("GET", f"/effects?page={page}&size={size}")
        return EffectPage.model_validate(data)

    async def get_effect(self, code: str) -> Effect:
        """Get effect details by code"""
        data = await self._request("GET", f"/effects/{code}")
        return Effect.model_validate(data)

    # ===== Events =====
    async def get_active_events(self, page: int = 1, size: int = 50) -> ActiveEventPage:
        """Get all active events"""
        data = await self._request("GET", f"/events/active?page={page}&size={size}")
        return ActiveEventPage.model_validate(data)

    async def get_events(
        self, event_type: Optional[str] = None, page: int = 1, size: int = 50
    ) -> EventPage:
        """Get all events"""
        params = [f"page={page}", f"size={size}"]
        if event_type:
            params.append(f"type={event_type}")
        endpoint = f"/events?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return EventPage.model_validate(data)

    async def spawn_event(self, code: str) -> ActiveEvent:
        """Spawn an event (requires event token)"""
        data = await self._request("POST", "/events/spawn", {"code": code})
        return ActiveEvent.model_validate(data)

    # ===== Grand Exchange =====
    async def get_ge_item_history(
        self,
        code: str,
        seller: Optional[str] = None,
        buyer: Optional[str] = None,
        page: int = 1,
        size: int = 50,
    ) -> GEOrderHistoryPage:
        """Get Grand Exchange sales history for an item (public)"""
        params = [f"page={page}", f"size={size}"]
        if seller:
            params.append(f"seller={seller}")
        if buyer:
            params.append(f"buyer={buyer}")
        endpoint = f"/grandexchange/history/{code}?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return GEOrderHistoryPage.model_validate(data)

    async def get_all_ge_orders(
        self,
        code: Optional[str] = None,
        seller: Optional[str] = None,
        page: int = 1,
        size: int = 50,
    ) -> GEOrderPage:
        """Get all Grand Exchange sell orders"""
        params = [f"page={page}", f"size={size}"]
        if code:
            params.append(f"code={code}")
        if seller:
            params.append(f"seller={seller}")
        endpoint = f"/grandexchange/orders?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return GEOrderPage.model_validate(data)

    async def get_ge_order(self, order_id: str) -> GEOrder:
        """Get a specific Grand Exchange order by ID"""
        data = await self._request("GET", f"/grandexchange/orders/{order_id}")
        return GEOrder.model_validate(data)

    # ===== Items =====
    async def get_items(
        self,
        name: str = None,
        min_level: Optional[int] = None,
        max_level: Optional[int] = None,
        item_type: Optional[str] = None,
        craft_skill: Optional[str] = None,
        craft_material: Optional[str] = None,
        page: int = 1,
        size: int = 50,
    ) -> ItemPage:
        """Get all items with optional filters"""
        params = [f"page={page}", f"size={size}"]
        if name:
            params.append(f"name={name}")
        if min_level is not None:
            params.append(f"min_level={min_level}")
        if max_level is not None:
            params.append(f"max_level={max_level}")
        if item_type:
            params.append(f"type={item_type}")
        if craft_skill:
            params.append(f"craft_skill={craft_skill}")
        if craft_material:
            params.append(f"craft_material={craft_material}")
        endpoint = f"/items?{'&'.join(params)}"
        data = await self._request_paginated("GET", endpoint)
        return ItemPage.model_validate(data)

    async def get_item(self, code: str) -> Item:
        """Get item details by code"""
        data = await self._request("GET", f"/items/{code}")
        return Item.model_validate(data)

    # ===== Leaderboards =====
    async def get_characters_leaderboard(
        self,
        sort: Optional[str] = None,
        name: str = None,
        page: int = 1,
        size: int = 50,
    ) -> CharacterLeaderboardPage:
        """Get characters leaderboard"""
        params = [f"page={page}", f"size={size}"]
        if sort:
            params.append(f"sort={sort}")
        if name:
            params.append(f"name={name}")
        endpoint = f"/leaderboard/characters?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return CharacterLeaderboardPage.model_validate(data)

    async def get_accounts_leaderboard(
        self,
        sort: Optional[str] = None,
        name: str = None,
        page: int = 1,
        size: int = 50,
    ) -> AccountLeaderboardPage:
        """Get accounts leaderboard"""
        params = [f"page={page}", f"size={size}"]
        if sort:
            params.append(f"sort={sort}")
        if name:
            params.append(f"name={name}")
        endpoint = f"/leaderboard/accounts?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return AccountLeaderboardPage.model_validate(data)

    # ===== Maps =====
    async def get_maps(
        self,
        layer: Optional[str] = None,
        content_type: Optional[str] = None,
        content_code: Optional[str] = None,
        hide_blocked_maps: bool = False,
        page: int = 1,
        size: int = 50,
    ) -> MapPage:
        """Get all maps with optional filters"""
        params = [f"page={page}", f"size={size}"]
        if layer:
            params.append(f"layer={layer}")
        if content_type:
            params.append(f"content_type={content_type}")
        if content_code:
            params.append(f"content_code={content_code}")
        if hide_blocked_maps:
            params.append("hide_blocked_maps=true")
        endpoint = f"/maps?{'&'.join(params)}"
        data = await self._request_paginated("GET", endpoint)
        return MapPage.model_validate(data)

    async def get_layer_maps(
        self,
        layer: str,
        content_type: Optional[str] = None,
        content_code: Optional[str] = None,
        hide_blocked_maps: bool = False,
        page: int = 1,
        size: int = 50,
    ) -> MapPage:
        """Get maps for a specific layer"""
        params = [f"page={page}", f"size={size}"]
        if content_type:
            params.append(f"content_type={content_type}")
        if content_code:
            params.append(f"content_code={content_code}")
        if hide_blocked_maps:
            params.append("hide_blocked_maps=true")
        endpoint = f"/maps/{layer}?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return MapPage.model_validate(data)

    async def get_map_by_position(self, layer: str, x: int, y: int) -> Map:
        """Get map by layer and coordinates"""
        data = await self._request("GET", f"/maps/{layer}/{x}/{y}")
        return Map.model_validate(data)

    async def get_map_by_id(self, map_id: int) -> Map:
        """Get map by ID"""
        data = await self._request("GET", f"/maps/id/{map_id}")
        return Map.model_validate(data)

    # ===== Monsters =====
    async def get_monsters(
        self,
        name: str = None,
        min_level: Optional[int] = None,
        max_level: Optional[int] = None,
        drop: Optional[str] = None,
        page: int = 1,
        size: int = 50,
    ) -> MonsterPage:
        """Get all monsters with optional filters"""
        params = [f"page={page}", f"size={size}"]
        if name:
            params.append(f"name={name}")
        if min_level is not None:
            params.append(f"min_level={min_level}")
        if max_level is not None:
            params.append(f"max_level={max_level}")
        if drop:
            params.append(f"drop={drop}")
        endpoint = f"/monsters?{'&'.join(params)}"
        data = await self._request_paginated("GET", endpoint)
        return MonsterPage.model_validate(data)

    async def get_monster(self, code: str) -> Monster:
        """Get monster details by code"""
        data = await self._request("GET", f"/monsters/{code}")
        return Monster.model_validate(data)

    # ===== NPCs =====
    async def get_npcs(
        self,
        name: str = None,
        npc_type: Optional[str] = None,
        page: int = 1,
        size: int = 50,
    ) -> NPCPage:
        """Get all NPCs with optional filters"""
        params = [f"page={page}", f"size={size}"]
        if name:
            params.append(f"name={name}")
        if npc_type:
            params.append(f"type={npc_type}")
        endpoint = f"/npcs/details?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return NPCPage.model_validate(data)

    async def get_npc(self, code: str) -> NPC:
        """Get NPC details by code"""
        data = await self._request("GET", f"/npcs/details/{code}")
        return NPC.model_validate(data)

    async def get_npc_items(
        self, code: str, page: int = 1, size: int = 50
    ) -> NPCItemPage:
        """Get items available from a specific NPC"""
        data = await self._request("GET", f"/npcs/items/{code}?page={page}&size={size}")
        return NPCItemPage.model_validate(data)

    async def get_all_npc_items(
        self,
        code: Optional[str] = None,
        npc: Optional[str] = None,
        currency: Optional[str] = None,
        page: int = 1,
        size: int = 50,
    ) -> NPCItemPage:
        """Get all NPC items across all NPCs"""
        params = [f"page={page}", f"size={size}"]
        if code:
            params.append(f"code={code}")
        if npc:
            params.append(f"npc={npc}")
        if currency:
            params.append(f"currency={currency}")
        endpoint = f"/npcs/items?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return NPCItemPage.model_validate(data)

    # ===== Resources =====
    async def get_resources(
        self,
        min_level: Optional[int] = None,
        max_level: Optional[int] = None,
        skill: Optional[str] = None,
        drop: Optional[str] = None,
        page: int = 1,
        size: int = 50,
    ) -> ResourcePage:
        """Get all resources with optional filters"""
        params = [f"page={page}", f"size={size}"]
        if min_level is not None:
            params.append(f"min_level={min_level}")
        if max_level is not None:
            params.append(f"max_level={max_level}")
        if skill:
            params.append(f"skill={skill}")
        if drop:
            params.append(f"drop={drop}")
        endpoint = f"/resources?{'&'.join(params)}"
        data = await self._request_paginated("GET", endpoint)
        return ResourcePage.model_validate(data)

    async def get_resource(self, code: str) -> Resource:
        """Get resource details by code"""
        data = await self._request("GET", f"/resources/{code}")
        return Resource.model_validate(data)

    # ===== Tasks =====
    async def get_all_tasks(
        self,
        min_level: Optional[int] = None,
        max_level: Optional[int] = None,
        skill: Optional[str] = None,
        task_type: Optional[str] = None,
        page: int = 1,
        size: int = 50,
    ) -> TaskFullPage:
        """Get all tasks with optional filters"""
        params = [f"page={page}", f"size={size}"]
        if min_level is not None:
            params.append(f"min_level={min_level}")
        if max_level is not None:
            params.append(f"max_level={max_level}")
        if skill:
            params.append(f"skill={skill}")
        if task_type:
            params.append(f"type={task_type}")
        endpoint = f"/tasks/list?{'&'.join(params)}"
        data = await self._request("GET", endpoint)
        return TaskFullPage.model_validate(data)

    async def get_task_details(self, code: str) -> TaskFull:
        """Get task details by code"""
        data = await self._request("GET", f"/tasks/list/{code}")
        return TaskFull.model_validate(data)

    async def get_tasks_rewards(
        self, page: int = 1, size: int = 50
    ) -> TaskRewardDropPage:
        """Get all possible task rewards (exchange 6 coins)"""
        data = await self._request("GET", f"/tasks/rewards?page={page}&size={size}")
        return TaskRewardDropPage.model_validate(data)

    async def get_task_reward(self, code: str) -> TaskRewardDrop:
        """Get specific task reward details"""
        data = await self._request("GET", f"/tasks/rewards/{code}")
        return TaskRewardDrop.model_validate(data)

    # ===== Simulation =====
    async def simulate_fight(
        self, characters: List[FakeCharacter], monster: str, iterations: int = 10
    ) -> CombatSimulation:
        """Simulate combat (requires member account)

        Args:
            characters: List of 1-3 fake characters to simulate
            monster: Monster code to fight against
            iterations: Number of combat simulations (1-100)
        """
        data = await self._request(
            "POST",
            "/simulation/fight_simulation",
            {
                "characters": [char.model_dump() for char in characters],
                "monster": monster,
                "iterations": iterations,
            },
        )
        return CombatSimulation.model_validate(data)

    # ===== Token =====
    @staticmethod
    async def generate_token(username: str, password: str) -> str:
        """Generate API token using username and password

        Note: This is a static method that creates a temporary client
        to authenticate and get a token.
        """
        import base64

        auth = base64.b64encode(f"{username}:{password}".encode()).decode()

        async with httpx.AsyncClient(
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
            timeout=10.0,
        ) as client:
            response = await client.post(f"{ArtifactsClient.BASE_URL}/token")
            response.raise_for_status()
            token_data = response.json()["data"]
            return TokenResponse.model_validate(token_data).token

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
