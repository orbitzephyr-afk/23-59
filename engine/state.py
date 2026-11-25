from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any

from .scenario import ScenarioData


@dataclass
class NPCState:
    id: str
    zone: str
    stats: dict[str, int]
    hearsay_resolve: int = 0
    items: list[str] = field(default_factory=list)
    used_tags: set[str] = field(default_factory=set)
    memory: list[str] = field(default_factory=list)
    tracking: str | None = None
    detained: bool = False
    forced_action: dict[str, Any] | None = None
    fallback_cursor: int = 0

    def add_memory(self, text: str, limit: int = 12) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        self.memory.append(cleaned)
        if len(self.memory) > limit:
            self.memory = self.memory[-limit:]


@dataclass
class LogEntry:
    turn: int
    clock: str
    npc: str
    tags_hit: list[str] = field(default_factory=list)
    delta: dict[str, int] = field(default_factory=dict)
    stats_after: dict[str, int] = field(default_factory=dict)
    thought: str = ""
    speech: str = ""
    proposed: dict[str, Any] = field(default_factory=dict)
    verdict: str = "PASS"
    reason: str = ""
    retry: dict[str, Any] | None = None
    forced: bool = False
    llm_ms: int = 0
    json_repaired: bool = False
    skipped_llm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "clock": self.clock,
            "npc": self.npc,
            "tags_hit": list(self.tags_hit),
            "delta": dict(self.delta),
            "stats_after": dict(self.stats_after),
            "thought": self.thought,
            "speech": self.speech,
            "proposed": dict(self.proposed),
            "verdict": self.verdict,
            "reason": self.reason,
            "retry": dict(self.retry) if self.retry else None,
            "forced": self.forced,
            "llm_ms": self.llm_ms,
            "json_repaired": self.json_repaired,
            "skipped_llm": self.skipped_llm,
        }


@dataclass
class GameState:
    session_id: str
    # ── 跨循环保留 ──
    loop_count: int = 1
    clues_unlocked: list[str] = field(default_factory=list)
    puzzle_slots: dict[str, str | None] = field(
        default_factory=lambda: {"1": None, "2": None, "3": None, "4": None}
    )
    puzzle_solved: bool = False
    notebook: list[str] = field(default_factory=list)
    endings_seen: list[str] = field(default_factory=list)
    # ── 本轮状态 ──
    turn: int = 1
    player_zone: str = "MID"
    player_items: list[str] = field(default_factory=list)
    player_waited: bool = False
    npcs: dict[str, NPCState] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)
    log: list[LogEntry] = field(default_factory=list)
    ending: dict[str, Any] | None = None

    def unlock_clue(self, clue_id: str) -> bool:
        if clue_id not in self.clues_unlocked:
            self.clues_unlocked.append(clue_id)
            return True
        return False

    def add_note(self, note: str) -> bool:
        cleaned = note.strip()
        if cleaned and cleaned not in self.notebook:
            self.notebook.append(cleaned)
            return True
        return False

    def record_ending(self, ending_id: str) -> None:
        if ending_id not in self.endings_seen:
            self.endings_seen.append(ending_id)


def _init_npcs(scenario: ScenarioData) -> dict[str, NPCState]:
    npcs: dict[str, NPCState] = {}
    for npc_id, cfg in scenario.characters.items():
        npcs[npc_id] = NPCState(
            id=npc_id,
            zone=cfg["start_zone"],
            stats=copy.deepcopy(cfg["stats"]),
            items=list(cfg.get("items", [])),
        )
    return npcs


def create_new_game(scenario: ScenarioData, session_id: str | None = None) -> GameState:
    state = GameState(
        session_id=session_id or uuid.uuid4().hex[:12],
        loop_count=1,
        clues_unlocked=list(scenario.world.get("initial_clues", [])),
        puzzle_slots={"1": None, "2": None, "3": None, "4": None},
        puzzle_solved=False,
        notebook=[],
        endings_seen=[],
        turn=1,
        player_zone=scenario.world["player_start_zone"],
        player_items=[],
        player_waited=False,
        npcs=_init_npcs(scenario),
        flags=copy.deepcopy(scenario.world["initial_flags"]),
        log=[],
        ending=None,
    )
    return state


def reset_loop(
    state: GameState,
    scenario: ScenarioData,
    skip_to_t2: bool = False,
    increment_loop: bool = True,
) -> list[dict[str, Any]]:
    """Reset per-loop state while preserving unlocked clues, puzzle, notebook, and loop count."""
    if increment_loop:
        state.loop_count += 1
    state.turn = 2 if skip_to_t2 else 1
    state.player_zone = scenario.world["player_start_zone"]
    state.player_items = []
    state.player_waited = False
    state.npcs = _init_npcs(scenario)
    state.flags = copy.deepcopy(scenario.world["initial_flags"])
    state.log = []
    state.ending = None

    intro_events: list[dict[str, Any]] = []
    if skip_to_t2:
        t2_info = scenario.timeline["turns"]["2"]
        ear = scenario.timeline["earphone_t2"]
        intro_events.append(
            {
                "kind": "broadcast",
                "actor": None,
                "target": None,
                "zone": None,
                "text": f"{t2_info['broadcast']}\n{t2_info['window_event']}",
            }
        )
        state.flags["last_broadcast_turn"] = 2
        intro_events.append(
            {
                "kind": "earphone",
                "actor": "player",
                "target": None,
                "zone": state.player_zone,
                "text": f"{ear['scene']}\n{ear['voice']}",
            }
        )
        newly_unlocked = state.unlock_clue("C0_EARPHONE_ECHO")
        state.flags["t2_earphone_done"] = True
        if newly_unlocked:
            intro_events.append(
                {
                    "kind": "clue_unlocked",
                    "actor": "player",
                    "target": "C0_EARPHONE_ECHO",
                    "zone": state.player_zone,
                    "text": f"解锁线索：{scenario.clues['C0_EARPHONE_ECHO']['name']}",
                }
            )
    else:
        t1_info = scenario.timeline["turns"]["1"]
        intro_events.append(
            {
                "kind": "broadcast",
                "actor": None,
                "target": None,
                "zone": None,
                "text": f"{t1_info['broadcast']}\n{t1_info['window_event']}",
            }
        )
        state.flags["last_broadcast_turn"] = 1
    return intro_events


def npc_public_status(npc: NPCState, flags: dict[str, Any]) -> str | None:
    if npc.detained:
        return "DETAINED"
    if npc.tracking == "zhou":
        return "TRACKING_ZHOU"
    if npc.id == "chen" and flags.get("logbook_handed"):
        return "CONFESSED"
    return None


def build_view(state: GameState, scenario: ScenarioData) -> dict[str, Any]:
    npcs_view = []
    for npc_id, npc in state.npcs.items():
        cfg = scenario.characters[npc_id]
        _, mood = scenario.get_state_words_and_mood(
            npc_id, npc.stats, npc.detained, state.flags, state.clues_unlocked
        )
        npcs_view.append(
            {
                "id": npc_id,
                "name": cfg["name"],
                "role": cfg.get("role", ""),
                "zone": npc.zone,
                "stats": dict(npc.stats),
                "mood": mood,
                "status": npc_public_status(npc, state.flags),
            }
        )

    clues_view = []
    for cid in state.clues_unlocked:
        c = scenario.clues.get(cid)
        if c:
            clues_view.append(
                {
                    "id": cid,
                    "name": c["name"],
                    "text": c["text"],
                    "puzzle_role": c.get("puzzle_role", "hint"),
                    "has_physical": bool(
                        c.get("physical_item") and c.get("physical_item") in state.player_items
                    ),
                }
            )

    hints_view = []
    for h in scenario.timeline.get("speech_hints", []):
        req = h.get("requires_clue")
        if req is None or req in state.clues_unlocked:
            hints_view.append(
                {
                    "id": h["id"],
                    "label": h["label"],
                    "prefill": h["prefill"],
                }
            )

    clock = (
        scenario.world["midnight_clock"]
        if state.ending is not None
        else scenario.clock_for_turn(state.turn)
    )

    return {
        "title": scenario.world["title"],
        "subtitle": scenario.world["subtitle"],
        "turn": state.turn,
        "max_turns": scenario.world["max_turns"],
        "clock": clock,
        "loop_count": state.loop_count,
        "zones": scenario.world["zones"],
        "player": {
            "zone": state.player_zone,
            "items": list(state.player_items),
        },
        "npcs": npcs_view,
        "clues": clues_view,
        "puzzle": {
            "slots": dict(state.puzzle_slots),
            "slots_meta": scenario.world["puzzle_slots_meta"],
            "solved": state.puzzle_solved,
        },
        "notebook": list(state.notebook),
        "speech_hints": hints_view,
        "can_skip_to_t2": state.loop_count > 1 or len(state.endings_seen) > 0,
        "awaiting_final_puzzle": bool(state.flags.get("awaiting_final_puzzle")),
        "endings_seen": list(state.endings_seen),
        "opening_narration": scenario.world.get("opening_narration", ""),
        "ending": state.ending,
    }


def build_inspector(state: GameState) -> dict[str, Any]:
    return {
        "turn": state.turn,
        "loop_count": state.loop_count,
        "flags": copy.deepcopy(state.flags),
        "memories": {npc_id: list(npc.memory) for npc_id, npc in state.npcs.items()},
        "items": {npc_id: list(npc.items) for npc_id, npc in state.npcs.items()},
        "player_items": list(state.player_items),
        "logs": [entry.to_dict() for entry in state.log],
    }
