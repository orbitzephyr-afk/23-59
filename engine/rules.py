from __future__ import annotations

from typing import Any

from .scenario import ScenarioData
from .state import GameState, NPCState


VALID_ZONES = {"FRONT", "MID", "REAR"}


def get_allowed_actions(
    state: GameState,
    npc: NPCState,
    scenario: ScenarioData,
) -> list[str]:
    """Build allowed actions for an NPC without pre-filtering zone for HIDE_OR_DESTROY / PULL_BRAKE
    so the rule engine can reject invalid-zone attempts and trigger retry decisions."""
    if npc.detained:
        return ["STAY"]

    actions = ["STAY", "MOVE"]

    same_zone_npcs = [
        other.id for other in state.npcs.values() if other.id != npc.id and other.zone == npc.zone
    ]
    if same_zone_npcs:
        actions.append("WHISPER")
    if same_zone_npcs or state.player_zone == npc.zone:
        actions.append("CONFRONT")

    panic = npc.stats.get("panic", 0)
    destroyable_items = [
        item_id
        for item_id in npc.items
        if scenario.items.get(item_id, {}).get("destroyable")
    ]
    if destroyable_items and panic >= 65:
        actions.append("HIDE_OR_DESTROY")

    if panic >= 90:
        actions.append("PULL_BRAKE")

    return actions


def validate_action(
    state: GameState,
    npc: NPCState,
    proposed: dict[str, Any],
    scenario: ScenarioData,
    *,
    forced: bool = False,
) -> tuple[str, str]:
    """Deterministic rule validation returning (verdict, reason).
    verdict is one of PASS / REJECTED / INTERCEPTED.
    """
    action = str(proposed.get("action") or "STAY").upper()
    target = proposed.get("target")

    if npc.detained and action != "STAY":
        return "REJECTED", "已被便衣警察控制，无法行动"

    if action in ("HAND_OVER", "DETAIN"):
        if forced:
            return "PASS", ""
        return "REJECTED", "该动作仅由系统关键节点触发"

    if action == "STAY":
        return "PASS", ""

    if action == "MOVE":
        if target in VALID_ZONES and target != npc.zone:
            return "PASS", ""
        return "REJECTED", "目标车厢区域无效或你已在该区域"

    if action == "WHISPER":
        other = state.npcs.get(str(target))
        if other and other.id != npc.id and other.zone == npc.zone:
            return "PASS", ""
        return "REJECTED", "对方不在这节车厢区域，无法私聊"

    if action == "CONFRONT":
        if target == "player" and state.player_zone == npc.zone:
            return "PASS", ""
        other = state.npcs.get(str(target))
        if other and other.id != npc.id and other.zone == npc.zone:
            return "PASS", ""
        return "REJECTED", "对方不在这节车厢区域"

    if action == "HIDE_OR_DESTROY":
        item_id = str(target or "")
        if item_id not in npc.items:
            # Default to first destroyable item held if LLM omitted target name cleanly
            destroyables = [
                i for i in npc.items if scenario.items.get(i, {}).get("destroyable")
            ]
            if not destroyables:
                return "REJECTED", "你手上没有可销毁的证物"
            item_id = destroyables[0]
            proposed["target"] = item_id

        if npc.stats.get("panic", 0) < 65:
            return "REJECTED", "尚未达到恐慌销毁阈值"

        destroy_zone = scenario.world.get("destroy_zone", "REAR")
        if npc.zone != destroy_zone:
            return "REJECTED", "只能在车尾垃圾箱销毁"

        lu = state.npcs.get("lu")
        if lu and lu.zone == npc.zone and state.flags.get("lu_active"):
            return "INTERCEPTED", "陆建军已亮证并在场，当场拦截并夺下审批单"

        return "PASS", "趁无人阻拦将证物销毁"

    if action == "PULL_BRAKE":
        if npc.stats.get("panic", 0) < 90:
            return "REJECTED", "尚未达到失控拉闸阈值"

        brake_zone = scenario.world.get("brake_zone", "FRONT")
        if npc.zone != brake_zone:
            return "REJECTED", "拉环只在车头"

        lu = state.npcs.get("lu")
        if lu and lu.zone == npc.zone:
            # Public safety exception: Lu intervenes even if not activated!
            return "INTERCEPTED", "陆建军就在车头，出于公共安全立刻出手拦下紧急制动"

        return "PASS", "紧急制动被强行拉下"

    return "REJECTED", f"未知动作：{action}"
