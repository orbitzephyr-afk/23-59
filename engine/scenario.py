from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
SCENARIO_DIR = ROOT_DIR / "scenario"
PROMPTS_DIR = ROOT_DIR / "prompts"


@dataclass(frozen=True)
class ScenarioData:
    world: dict[str, Any]
    characters: dict[str, dict[str, Any]]
    items: dict[str, dict[str, Any]]
    clues: dict[str, dict[str, Any]]
    tags: dict[str, dict[str, Any]]
    timeline: dict[str, Any]
    endings: dict[str, dict[str, Any]]
    npc_prompt_template: str
    tagger_prompt_template: str

    def clock_for_turn(self, turn: int) -> str:
        return self.world["clocks"].get(str(turn), self.world["midnight_clock"])

    def zone_name(self, zone_id: str) -> str:
        return self.world["zone_names"].get(zone_id, zone_id)

    def char_name(self, npc_id: str) -> str:
        char = self.characters.get(npc_id)
        return char["name"] if char else npc_id

    def eval_condition(
        self,
        condition: str,
        npc_stats: dict[str, int],
        detained: bool,
        flags: dict[str, Any],
        clues_unlocked: list[str],
    ) -> bool:
        if condition == "default":
            return True
        if condition == "detained":
            return detained
        if condition == "logbook_handed":
            return bool(flags.get("logbook_handed"))
        if condition == "lu_active":
            return bool(flags.get("lu_active"))
        if condition == "lin_forgave_and_target_zhou":
            return bool(flags.get("lin_forgave")) and flags.get("lin_target") == "zhou"
        if condition == "lin_forgave_only":
            return bool(flags.get("lin_forgave")) and flags.get("lin_target") != "zhou"
        if condition == "lin_target_zhou":
            return flags.get("lin_target") == "zhou"
        if condition == "guard<=45_or_c5":
            return npc_stats.get("guard", 100) <= 45 or "C5_LIN_IDENTITY" in clues_unlocked

        for op in (">=", "<=", ">", "<", "=="):
            if op in condition:
                left, right = condition.split(op, 1)
                val = npc_stats.get(left.strip(), 0)
                target = int(right.strip())
                if op == ">=":
                    return val >= target
                if op == "<=":
                    return val <= target
                if op == ">":
                    return val > target
                if op == "<":
                    return val < target
                if op == "==":
                    return val == target
        return False

    def get_disclosable(
        self,
        npc_id: str,
        npc_stats: dict[str, int],
        detained: bool,
        flags: dict[str, Any],
        clues_unlocked: list[str],
    ) -> str:
        tiers = self.characters[npc_id].get("disclosure_tiers", [])
        for tier in tiers:
            if self.eval_condition(tier["condition"], npc_stats, detained, flags, clues_unlocked):
                return tier["disclosable"]
        return "无，继续隐瞒。"

    def get_state_words_and_mood(
        self,
        npc_id: str,
        npc_stats: dict[str, int],
        detained: bool,
        flags: dict[str, Any],
        clues_unlocked: list[str],
    ) -> tuple[str, str]:
        entries = self.characters[npc_id].get("state_words", [])
        for entry in entries:
            if self.eval_condition(entry["condition"], npc_stats, detained, flags, clues_unlocked):
                return entry["text"], entry.get("mood", "平静")
        return "保持冷静观察。", "平静"


_CACHED_SCENARIO: ScenarioData | None = None


def load_scenario(force_reload: bool = False) -> ScenarioData:
    global _CACHED_SCENARIO
    if _CACHED_SCENARIO is not None and not force_reload:
        return _CACHED_SCENARIO

    def _read_json(name: str) -> Any:
        return json.loads((SCENARIO_DIR / name).read_text(encoding="utf-8"))

    _CACHED_SCENARIO = ScenarioData(
        world=_read_json("world.json"),
        characters=_read_json("characters.json"),
        items=_read_json("items.json"),
        clues=_read_json("clues.json"),
        tags=_read_json("tags.json"),
        timeline=_read_json("timeline.json"),
        endings=_read_json("endings.json"),
        npc_prompt_template=(PROMPTS_DIR / "npc.txt").read_text(encoding="utf-8"),
        tagger_prompt_template=(PROMPTS_DIR / "tagger.txt").read_text(encoding="utf-8"),
    )
    return _CACHED_SCENARIO
