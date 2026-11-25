from __future__ import annotations

import asyncio
from typing import Any

from .llm import LLMClient
from .scenario import ScenarioData
from .state import GameState


def evaluate_puzzle(
    state: GameState,
    slots: dict[str, str | None],
    scenario: ScenarioData,
) -> tuple[bool, str]:
    solution = scenario.world["puzzle_solution"]
    msgs = scenario.world["puzzle_messages"]

    normalized: dict[str, str | None] = {}
    for k in ("1", "2", "3", "4"):
        val = slots.get(k)
        if val is not None and val in state.clues_unlocked:
            normalized[k] = val
        else:
            normalized[k] = None

    state.puzzle_slots = normalized

    if any(normalized[k] is None for k in ("1", "2", "3", "4")):
        state.puzzle_solved = False
        return False, msgs["incomplete"]

    if all(normalized[k] == solution[k] for k in ("1", "2", "3", "4")):
        state.puzzle_solved = True
        return True, msgs["solved"]

    state.puzzle_solved = False
    return False, msgs["wrong"]


def determine_midnight_ending_id(state: GameState) -> str:
    """Top-to-bottom deterministic ending match at 00:00."""
    if not state.puzzle_solved:
        return "A"

    secured = state.flags.get("approval_slip_status") == "SECURED"
    handed = bool(state.flags.get("logbook_handed"))
    forgave = bool(state.flags.get("lin_forgave"))

    if secured and handed and forgave:
        return "D"
    if secured and handed and not forgave:
        return "C"
    return "B"


async def _generate_farewell(
    ending_id: str,
    npc_id: str,
    state: GameState,
    scenario: ScenarioData,
    llm: LLMClient,
    user_token: str | None = None,
) -> dict[str, str]:
    ending_cfg = scenario.endings[ending_id]
    fallback = ending_cfg.get("mock_farewells", {}).get(npc_id, "……")
    if llm.is_mock(user_token):
        return {"npc": npc_id, "name": scenario.char_name(npc_id), "text": fallback}

    char_cfg = scenario.characters[npc_id]
    npc = state.npcs[npc_id]
    mem = "\n".join(f"- {m}" for m in npc.memory[-6:]) if npc.memory else "- 无特别记忆"
    sys_prompt = (
        f"你在扮演《23:59》里的{char_cfg['name']}（{char_cfg.get('role', '')}）。"
        f"说话风格：{char_cfg['speech_style']}。"
        f"现在列车刚刚跨过 00:00，迎来结局【{ending_cfg['title']}】：{ending_cfg['narration']}\n"
        f"请结合你本轮的记忆，只说一句 40 字以内的终局告别独白，直接输出纯台词，不要加引号或解释。"
    )
    try:
        raw, _ = await llm.complete(
            sys_prompt,
            f"你的本轮记忆：\n{mem}",
            role_kind="npc",
            npc_id=npc_id,
            user_token=user_token,
            temperature=0.7,
            max_tokens=100,
        )
        text = raw.strip().strip("“”\"'")
        return {"npc": npc_id, "name": char_cfg["name"], "text": text or fallback}
    except Exception:
        return {"npc": npc_id, "name": char_cfg["name"], "text": fallback}


async def build_ending_payload(
    ending_id: str,
    state: GameState,
    scenario: ScenarioData,
    llm: LLMClient,
    user_token: str | None = None,
) -> dict[str, Any]:
    cfg = scenario.endings[ending_id]
    farewells = await asyncio.gather(
        *[
            _generate_farewell(ending_id, npc_id, state, scenario, llm, user_token=user_token)
            for npc_id in ("zhou", "chen", "lin", "lu")
        ]
    )
    state.record_ending(ending_id)
    payload = {
        "id": ending_id,
        "title": cfg["title"],
        "narration": cfg["narration"],
        "visual": cfg["visual"],
        "farewells": list(farewells),
    }
    state.ending = payload
    return payload
