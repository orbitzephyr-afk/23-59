from __future__ import annotations

import asyncio
from typing import Any

from .endings import build_ending_payload, determine_midnight_ending_id
from .llm import LLMClient
from .npc import decide_for_npc
from .rules import VALID_ZONES
from .scenario import ScenarioData
from .state import GameState, LogEntry, NPCState, reset_loop
from .tagger import extract_tags


class TurnInputError(ValueError):
    """Raised when player submits an illegal move/action (mapped to HTTP 400)."""


def _clamp(val: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, val))


def _apply_capped_delta(
    npc: NPCState,
    stat: str,
    delta: int,
    start_stats: dict[str, dict[str, int]],
    raw_deltas: dict[str, dict[str, int]],
    cap: int,
    uncapped_bonuses: dict[str, dict[str, int]] | None = None,
) -> int:
    """Apply a stat change subject to the per-turn ±cap and [0, 100] bounds. Returns effective delta."""
    if stat not in npc.stats or delta == 0:
        return 0
    before = npc.stats[stat]
    raw_deltas[npc.id][stat] = raw_deltas[npc.id].get(stat, 0) + delta
    clamped_turn_delta = max(-cap, min(cap, raw_deltas[npc.id][stat]))
    bonus = uncapped_bonuses[npc.id].get(stat, 0) if uncapped_bonuses else 0
    npc.stats[stat] = _clamp(start_stats[npc.id][stat] + bonus + clamped_turn_delta, 0, 100)
    return npc.stats[stat] - before


def _clue_tags_for_target(clue_id: str | None, npc_id: str, scenario: ScenarioData) -> list[str]:
    if not clue_id or clue_id not in scenario.clues:
        return []
    pt = scenario.clues[clue_id].get("present_tags", {})
    if npc_id in pt:
        return list(pt[npc_id])
    return list(pt.get("default", []))


def _should_call_llm(
    npc: NPCState,
    state: GameState,
    action_type: str,
    action_target: str | None,
    script_involved: set[str],
    lu_just_badged: bool,
) -> bool:
    if npc.id == "lu":
        if not state.flags.get("lu_active"):
            # Unactivated Lu only calls LLM if player spoke directly to him
            return action_type == "SPEAK_PRIVATE" and action_target == "lu"
        # Activated Lu only needs LLM speech on milestone moments (badge / detain)
        if lu_just_badged or (npc.forced_action and npc.forced_action["action"] == "DETAIN"):
            return True
        if action_type == "SPEAK_PRIVATE" and action_target == "lu":
            return True
        return False

    if state.player_zone == npc.zone:
        return True
    if action_type == "SPEAK_PUBLIC":
        return True
    if npc.forced_action is not None:
        return True
    if npc.id in script_involved:
        return True
    if npc.stats.get("panic", 0) >= 65:
        return True
    return False


async def finalize_midnight(
    state: GameState,
    scenario: ScenarioData,
    llm: LLMClient,
    user_token: str | None = None,
) -> list[dict[str, Any]]:
    """Resolve 00:00 ending after T8 (used both directly at end of T8 and after final puzzle modal)."""
    state.flags["awaiting_final_puzzle"] = False
    ending_id = determine_midnight_ending_id(state)
    events: list[dict[str, Any]] = []
    if ending_id == "A":
        state.record_ending("A")
        events.append(
            {
                "kind": "loop_reset",
                "actor": None,
                "target": None,
                "zone": None,
                "text": scenario.endings["A"]["narration"],
            }
        )
        reset_loop(state, scenario, skip_to_t2=False, increment_loop=True)
        return events

    ending_payload = await build_ending_payload(
        ending_id, state, scenario, llm, user_token=user_token
    )
    events.append(
        {
            "kind": "midnight",
            "actor": None,
            "target": ending_id,
            "zone": None,
            "text": ending_payload["narration"],
            "ending": ending_payload,
        }
    )
    return events


async def process_turn(
    state: GameState,
    move: str | None,
    action: dict[str, Any],
    scenario: ScenarioData,
    llm: LLMClient,
    *,
    user_token: str | None = None,
    force_resolve_t8: bool = False,
) -> list[dict[str, Any]]:
    """Execute one complete turn strictly following Section 3 (Steps 1-10) of v1.1 spec."""
    if state.ending is not None:
        raise TurnInputError("本轮已抵达结局，请点击重新开始进入下一轮。")
    if state.flags.get("awaiting_final_puzzle"):
        raise TurnInputError("已到达 23:59 终局拼图确认，请先完成拼图或选择跨入 00:00。")

    action_type = str(action.get("type") or "").upper().strip()
    action_target = action.get("target")
    text = str(action.get("text") or "").strip()
    clue_id = action.get("clue_id") or None

    if action_type not in {"SPEAK_PRIVATE", "SPEAK_PUBLIC", "OBSERVE", "WAIT"}:
        raise TurnInputError("无效的玩家动作类型。")
    if move is not None and move not in VALID_ZONES:
        raise TurnInputError("无效的车厢区域，请选择车头、中段或车尾。")
    if clue_id is not None and clue_id not in state.clues_unlocked:
        raise TurnInputError("你尚未解锁该线索牌，无法出示。")

    # Pre-validate target zone against prospective player zone (after move)
    prospective_zone = move if move else state.player_zone
    if action_type in {"SPEAK_PRIVATE", "OBSERVE"}:
        if action_target not in state.npcs:
            raise TurnInputError("请选择一位有效的对话或观察对象。")
        if state.npcs[action_target].zone != prospective_zone:
            raise TurnInputError(
                f"{scenario.char_name(action_target)}不在{scenario.zone_name(prospective_zone)}，请先移动过去。"
            )
    if action_type == "SPEAK_PRIVATE" and not text and not clue_id:
        raise TurnInputError("请输入想说的话，或选择一张线索牌出示。")
    if action_type == "SPEAK_PUBLIC" and not text and not clue_id:
        raise TurnInputError("公开发言不能为空，请输入内容或选择线索牌。")

    events: list[dict[str, Any]] = []
    cap = int(scenario.world.get("per_turn_stat_cap", 30))
    mem_limit = int(scenario.world.get("memory_limit", 12))
    hearsay_cap = int(scenario.world.get("lu_hearsay_cap", 45))
    lu_threshold = int(scenario.world.get("lu_resolve_threshold", 70))
    lu_physical_bonus = int(scenario.world.get("lu_physical_bonus", 70))

    clock = scenario.clock_for_turn(state.turn)
    start_stats = {nid: dict(npc.stats) for nid, npc in state.npcs.items()}
    raw_deltas: dict[str, dict[str, int]] = {nid: {} for nid in state.npcs}
    uncapped_bonuses: dict[str, dict[str, int]] = {nid: {} for nid in state.npcs}
    npc_tags_hit: dict[str, list[str]] = {nid: [] for nid in state.npcs}
    player_visible_inputs: dict[str, list[str]] = {nid: [] for nid in state.npcs}

    for npc in state.npcs.values():
        npc.forced_action = None
    state.player_waited = False

    # ── Step 1: Turn-start event (T2 earphone if not yet emitted) ──
    if state.turn == 2 and not state.flags.get("t2_earphone_done"):
        ear = scenario.timeline["earphone_t2"]
        events.append(
            {
                "kind": "earphone",
                "actor": "player",
                "target": None,
                "zone": state.player_zone,
                "text": f"{ear['scene']}\n{ear['voice']}",
            }
        )
        state.flags["t2_earphone_done"] = True
        if state.unlock_clue("C0_EARPHONE_ECHO"):
            events.append(
                {
                    "kind": "clue_unlocked",
                    "actor": "player",
                    "target": "C0_EARPHONE_ECHO",
                    "zone": state.player_zone,
                    "text": f"解锁线索：{scenario.clues['C0_EARPHONE_ECHO']['name']}",
                }
            )

    # ── Step 2: Player move ──
    if move and move != state.player_zone:
        state.player_zone = move
        events.append(
            {
                "kind": "move",
                "actor": "player",
                "target": move,
                "zone": move,
                "text": f"你起身走到了{scenario.zone_name(move)}。",
            }
        )

    # ── Step 3 & Step 4: Player main action + Tag extraction + Table stat calculation ──
    text_tags = await extract_tags(text, scenario, llm, user_token=user_token) if text else []

    if action_type == "WAIT":
        state.player_waited = True
        wait_text = (
            "你压低帽檐缩在车尾角落座椅里假装睡死，竖起耳朵留意四周动静。"
            if state.player_zone == "REAR"
            else "你保持沉默，不动声色地观察车厢里每个人的举动。"
        )
        events.append(
            {
                "kind": "speech",
                "actor": "player",
                "target": None,
                "zone": state.player_zone,
                "text": wait_text,
            }
        )

    elif action_type == "OBSERVE":
        target_npc = state.npcs[action_target]
        hint = scenario.characters[action_target]["observe_hint"]
        state.add_note(hint)
        events.append(
            {
                "kind": "observe",
                "actor": "player",
                "target": action_target,
                "zone": state.player_zone,
                "text": hint,
            }
        )
        if action_target == "lin" and state.unlock_clue("C2_HALF_TESTIMONY"):
            events.append(
                {
                    "kind": "clue_unlocked",
                    "actor": "player",
                    "target": "C2_HALF_TESTIMONY",
                    "zone": state.player_zone,
                    "text": f"解锁线索：{scenario.clues['C2_HALF_TESTIMONY']['name']}",
                }
            )

    elif action_type in {"SPEAK_PRIVATE", "SPEAK_PUBLIC"}:
        clue_name = scenario.clues[clue_id]["name"] if clue_id else None
        if action_type == "SPEAK_PRIVATE":
            listeners = [action_target]
            display = f"你低声对{scenario.char_name(action_target)}说："
        else:
            listeners = list(state.npcs.keys())
            display = "你对着整节车厢朗声说："

        parts = []
        if clue_name:
            parts.append(f"【出示：{clue_name}】")
        if text:
            parts.append(f"“{text}”")
        player_line = display + " ".join(parts)
        events.append(
            {
                "kind": "speech",
                "actor": "player",
                "target": action_target if action_type == "SPEAK_PRIVATE" else "all",
                "zone": state.player_zone,
                "text": player_line,
            }
        )

        for lid in listeners:
            npc = state.npcs[lid]
            same_zone = npc.zone == state.player_zone
            # Clue is only visible to listeners in the same zone
            visible_clue = clue_id if same_zone else None

            mem_msg = f"[{clock}] 乘客" + ("对你" if action_type == "SPEAK_PRIVATE" else "公开") + "说："
            if visible_clue:
                mem_msg += f"[出示了{clue_name}] "
            if text:
                mem_msg += text
            npc.add_memory(mem_msg, limit=mem_limit)
            player_visible_inputs[lid].append(mem_msg)

            # Physical proof rule (Section 0.4): showing C6/C7 while actually holding ITEM_LOGBOOK this loop
            if (
                lid == "lu"
                and visible_clue in {"C6_K14_HAZARD", "C7_BADGE_LAST_WORDS"}
                and "ITEM_LOGBOOK" in state.player_items
                and not state.flags.get("lu_physical_seen")
            ):
                uncapped_bonuses["lu"]["resolve"] = uncapped_bonuses["lu"].get("resolve", 0) + lu_physical_bonus
                npc.stats["resolve"] = _clamp(
                    start_stats["lu"]["resolve"]
                    + uncapped_bonuses["lu"]["resolve"]
                    + max(-cap, min(cap, raw_deltas["lu"].get("resolve", 0))),
                    0,
                    100,
                )
                state.flags["lu_physical_seen"] = True
                npc.add_memory(
                    f"[{clock}] 乘客向你展示了老赵真实的检修记录本（K14+200 绝缘 0.3MΩ）与旧工牌实物。",
                    limit=mem_limit,
                )

            combined_tags: list[str] = []
            for t in text_tags + _clue_tags_for_target(visible_clue, lid, scenario):
                if t not in combined_tags:
                    combined_tags.append(t)

            # Ensure deterministic ordering so TAG_LAST_WORDS clearing chen never wipes TAG_BRIBE_10W -> zhou
            def _tag_sort_key(tag_id: str) -> int:
                if tag_id == "TAG_LAST_WORDS":
                    return 0
                if tag_id == "TAG_BRIBE_10W":
                    return 1
                return 2

            for tag_id in sorted(combined_tags, key=_tag_sort_key):
                if tag_id in npc.used_tags:
                    continue
                npc.used_tags.add(tag_id)
                npc_tags_hit[lid].append(tag_id)
                tag_cfg = scenario.tags[tag_id]

                # Apply stat effects
                if lid == "lin" and tag_id == "TAG_LAST_WORDS" and visible_clue == "C7_BADGE_LAST_WORDS":
                    effs = tag_cfg.get("lin_with_c7_effects", {})
                else:
                    effs = tag_cfg.get("effects", {}).get(lid, {})

                for stat_name, delta in effs.items():
                    if lid == "lu" and stat_name == "resolve":
                        remaining_hearsay = max(0, hearsay_cap - npc.hearsay_resolve)
                        applied = min(delta, remaining_hearsay)
                        if applied > 0:
                            npc.hearsay_resolve += applied
                            _apply_capped_delta(npc, "resolve", applied, start_stats, raw_deltas, cap, uncapped_bonuses)
                    else:
                        _apply_capped_delta(npc, stat_name, delta, start_stats, raw_deltas, cap, uncapped_bonuses)

                # Tag side effects
                if lid == "lin" and tag_id in {"TAG_LANLAN", "TAG_LIN_IDENTITY"}:
                    if state.unlock_clue("C5_LIN_IDENTITY"):
                        events.append(
                            {
                                "kind": "clue_unlocked",
                                "actor": "lin",
                                "target": "C5_LIN_IDENTITY",
                                "zone": npc.zone,
                                "text": f"解锁线索：{scenario.clues['C5_LIN_IDENTITY']['name']}",
                            }
                        )
                if lid == "lin" and tag_id == "TAG_LAST_WORDS" and visible_clue == "C7_BADGE_LAST_WORDS":
                    state.flags["lin_forgave"] = True
                    if state.flags.get("lin_target") == "chen":
                        state.flags["lin_target"] = None
                if lid == "lin" and tag_id == "TAG_BRIBE_10W":
                    state.flags["lin_target"] = "zhou"

    # ── Step 5: Scripted timeline events ──
    script_involved: set[str] = set()
    turn_meta = scenario.timeline["turns"][str(state.turn)]
    if state.flags.get("last_broadcast_turn") != state.turn:
        state.flags["last_broadcast_turn"] = state.turn
        events.append(
            {
                "kind": "broadcast",
                "actor": None,
                "target": None,
                "zone": None,
                "text": f"{turn_meta['broadcast']}\n{turn_meta['window_event']}",
            }
        )

    zhou = state.npcs["zhou"]
    chen = state.npcs["chen"]
    lin = state.npcs["lin"]
    lu = state.npcs["lu"]

    if state.turn == 3:
        if zhou.stats.get("panic", 0) < 65 and not zhou.detained and zhou.zone != "REAR":
            zhou.forced_action = {"action": "MOVE", "target": "REAR"}
            script_involved.add("zhou")

    elif state.turn == 4:
        if zhou.zone == "REAR" and chen.zone == "REAR" and not zhou.detained:
            script_involved.update({"zhou", "chen"})
            wcfg = scenario.timeline["t4_whisper"]
            if state.player_zone == "REAR" and not state.player_waited:
                events.append(
                    {
                        "kind": "whisper_seen",
                        "actor": "zhou",
                        "target": "chen",
                        "zone": "REAR",
                        "text": wcfg["cancelled_awake"],
                    }
                )
                zhou.add_memory(f"[{clock}] 车尾有乘客醒着盯着，取消了和陈默密谈。", limit=mem_limit)
            else:
                state.flags["t4_whisper_done"] = True
                zhou.add_memory(
                    f"[{clock}] 你在车尾低声警告陈默：十万手术费不是白垫的，烧掉巡检单，审批单你今晚去销。",
                    limit=mem_limit,
                )
                chen.add_memory(
                    f"[{clock}] 周明远在车尾威胁你：拿十万手术费和伪证逼你闭嘴，命你烧掉巡检单。",
                    limit=mem_limit,
                )
                if state.player_zone == "REAR" and state.player_waited:
                    for line in wcfg["script"]:
                        spk = line["speaker"]
                        events.append(
                            {
                                "kind": "whisper_heard",
                                "actor": spk,
                                "target": "chen" if spk == "zhou" else "zhou",
                                "zone": "REAR",
                                "text": f"【偷听】{scenario.char_name(spk)}：“{line['text']}”",
                            }
                        )
                    state.add_note(wcfg["notebook_summary"])
                    if state.unlock_clue("C3_WHISPER_BRIBE"):
                        events.append(
                            {
                                "kind": "clue_unlocked",
                                "actor": "player",
                                "target": "C3_WHISPER_BRIBE",
                                "zone": "REAR",
                                "text": f"解锁线索：{scenario.clues['C3_WHISPER_BRIBE']['name']}",
                            }
                        )
                else:
                    events.append(
                        {
                            "kind": "whisper_seen",
                            "actor": "zhou",
                            "target": "chen",
                            "zone": "REAR",
                            "text": wcfg["seen_from_afar"],
                        }
                    )

    elif state.turn == 5:
        if zhou.stats.get("panic", 0) < 65 and not zhou.detained and zhou.zone != "FRONT":
            zhou.forced_action = {"action": "MOVE", "target": "FRONT"}
            script_involved.add("zhou")
        if state.flags.get("lin_target") == "chen" and lin.zone != "REAR":
            lin.forced_action = {"action": "MOVE", "target": "REAR"}
            script_involved.add("lin")

    elif state.turn == 6:
        if (
            lin.zone == "REAR"
            and chen.zone == "REAR"
            and state.flags.get("lin_target") == "chen"
        ):
            lin.forced_action = {"action": "CONFRONT", "target": "chen"}
            script_involved.update({"lin", "chen"})
            _apply_capped_delta(chen, "guard", 20, start_stats, raw_deltas, cap)
            _apply_capped_delta(chen, "panic", 25, start_stats, raw_deltas, cap)

    # ── Step 6: Forced key milestones (strict priority order) ──
    lu_just_badged = False

    # 6.1 Chen HAND_OVER
    if (
        not state.flags.get("logbook_handed")
        and chen.stats.get("guilt", 0) >= 75
        and chen.stats.get("guard", 100) <= 35
        and state.player_zone == chen.zone
        and "ITEM_LOGBOOK" in chen.items
    ):
        chen.forced_action = {"action": "HAND_OVER", "target": "ITEM_LOGBOOK"}
        state.flags["logbook_handed"] = True
        chen.items.remove("ITEM_LOGBOOK")
        if "ITEM_LOGBOOK" not in state.player_items:
            state.player_items.append("ITEM_LOGBOOK")

    # 6.2 Lu sees physical proof via Chen in same zone
    if (
        state.flags.get("logbook_handed")
        and chen.zone == lu.zone
        and not state.flags.get("lu_physical_seen")
    ):
        uncapped_bonuses["lu"]["resolve"] = uncapped_bonuses["lu"].get("resolve", 0) + lu_physical_bonus
        lu.stats["resolve"] = _clamp(
            start_stats["lu"]["resolve"]
            + uncapped_bonuses["lu"]["resolve"]
            + max(-cap, min(cap, raw_deltas["lu"].get("resolve", 0))),
            0,
            100,
        )
        state.flags["lu_physical_seen"] = True
        lu.add_memory(
            f"[{clock}] 陈默当面交出老赵检修记录本并准备指证周明远。",
            limit=mem_limit,
        )

    # 6.3 Lu badge activation
    if lu.stats.get("resolve", 0) >= lu_threshold and not state.flags.get("lu_active"):
        state.flags["lu_active"] = True
        lu.tracking = "zhou"
        lu_just_badged = True
        events.append(
            {
                "kind": "badge",
                "actor": "lu",
                "target": "zhou",
                "zone": lu.zone,
                "text": "陆建军缓缓睁开眼，从夹克内袋掏出藏青色警官证亮明身份：“市局便衣。这事我接管了。”",
            }
        )
        for npc in state.npcs.values():
            npc.add_memory(f"[{clock}] 陆建军亮出警官证接管车厢现场，并开始盯紧周明远。", limit=mem_limit)

    # 6.4 Lin tracks & confronts Zhou
    lin_confronted_zhou = False
    if state.flags.get("lin_target") == "zhou":
        lin.tracking = "zhou"
        if lin.zone == zhou.zone and not zhou.detained:
            lin.forced_action = {"action": "CONFRONT", "target": "zhou"}
            lin_confronted_zhou = True
            _apply_capped_delta(zhou, "panic", 30, start_stats, raw_deltas, cap)
            zhou.add_memory(f"[{clock}] 林岚举着录音笔当众质问你审批单和半年前的真相！", limit=mem_limit)
            player_visible_inputs["zhou"].append(f"[{clock}] 林岚举着录音笔冲上来当众质问你审批单黑幕！")

    # 6.5 Lu DETAIN Zhou (same-turn immediate execution!)
    if (
        state.flags.get("lu_active")
        and not zhou.detained
        and lu.zone == zhou.zone
        and state.flags.get("logbook_handed")
        and lin.zone == zhou.zone
        and (state.flags.get("lin_target") == "zhou" or state.flags.get("lin_forgave"))
        and zhou.stats.get("panic", 0) >= 75
    ):
        lu.forced_action = {"action": "DETAIN", "target": "zhou"}
        zhou.forced_action = None

    # ── Step 7 & Step 8: Concurrent NPC decisions + Rule validation & retry ──
    llm_tasks: dict[str, asyncio.Task[dict[str, Any]]] = {}
    for npc_id, npc in state.npcs.items():
        if _should_call_llm(npc, state, action_type, action_target, script_involved, lu_just_badged):
            obs_lines = player_visible_inputs[npc_id]
            if not obs_lines:
                obs_lines = [f"[{clock}] 当前在{scenario.zone_name(npc.zone)}，车厢灯牌疾速飞掠。"]
            user_prompt = "本回合你看到和听到的事：\n" + "\n".join(obs_lines)
            llm_tasks[npc_id] = asyncio.create_task(
                decide_for_npc(state, npc, scenario, llm, user_prompt, user_token=user_token)
            )

    decisions: dict[str, dict[str, Any]] = {}
    if llm_tasks:
        results = await asyncio.gather(*llm_tasks.values())
        for npc_id, res in zip(llm_tasks.keys(), results):
            decisions[npc_id] = res

    # Fill skipped NPCs with lightweight default decisions (0 LLM calls)
    for npc_id, npc in state.npcs.items():
        if npc_id not in decisions:
            if npc.forced_action:
                act = npc.forced_action["action"]
                tgt = npc.forced_action.get("target")
                decisions[npc_id] = {
                    "proposed": {"action": act, "target": tgt},
                    "verdict": "PASS",
                    "reason": "",
                    "retry": None,
                    "final": {"thought": "", "speech": "", "speech_to": "none", "action": act, "target": tgt},
                    "final_verdict": "PASS",
                    "final_reason": "",
                    "llm_ms": 0,
                    "json_repaired": False,
                    "forced": True,
                    "skipped_llm": True,
                }
            else:
                decisions[npc_id] = {
                    "proposed": {"action": "STAY", "target": None},
                    "verdict": "PASS",
                    "reason": "",
                    "retry": None,
                    "final": {"thought": "", "speech": "", "speech_to": "none", "action": "STAY", "target": None},
                    "final_verdict": "PASS",
                    "final_reason": "",
                    "llm_ms": 0,
                    "json_repaired": False,
                    "forced": False,
                    "skipped_llm": True,
                }

    # ── Step 9: Three-phase execution ──
    # 9.1 Law enforcement first (DETAIN & INTERCEPTED)
    neutralized: set[str] = set()

    if decisions["lu"]["final"]["action"] == "DETAIN" and decisions["lu"]["final_verdict"] == "PASS":
        zhou.detained = True
        neutralized.add("zhou")
        state.flags["approval_slip_status"] = "SECURED"
        if "ITEM_APPROVAL_SLIP" in zhou.items:
            zhou.items.remove("ITEM_APPROVAL_SLIP")
        events.append(
            {
                "kind": "detain",
                "actor": "lu",
                "target": "zhou",
                "zone": lu.zone,
                "text": "陆建军一步上前依法控制住周明远，从公文包夹层当场查扣《免停运强行通车审批单》原件，背面竟赫然夹着寄给林岚匿名信的快递底单！",
            }
        )
        if state.unlock_clue("C4_APPROVAL_SLIP"):
            events.append(
                {
                    "kind": "clue_unlocked",
                    "actor": "lu",
                    "target": "C4_APPROVAL_SLIP",
                    "zone": lu.zone,
                    "text": f"解锁线索：{scenario.clues['C4_APPROVAL_SLIP']['name']}",
                }
            )

    for npc_id, dec in decisions.items():
        if npc_id in neutralized:
            continue
        if dec["final_verdict"] == "INTERCEPTED":
            act = dec["final"]["action"]
            if act == "HIDE_OR_DESTROY":
                zhou.detained = True
                neutralized.add(npc_id)
                state.flags["approval_slip_status"] = "SECURED"
                if "ITEM_APPROVAL_SLIP" in zhou.items:
                    zhou.items.remove("ITEM_APPROVAL_SLIP")
                events.append(
                    {
                        "kind": "intercepted",
                        "actor": "lu",
                        "target": npc_id,
                        "zone": state.npcs[npc_id].zone,
                        "text": "周明远刚掏出审批单欲塞进车尾垃圾箱销毁，身后的陆建军闪电般扣住他手腕！公文包落地，审批单原件与背面寄给林岚的匿名快递底单彻底曝光！",
                    }
                )
                if state.unlock_clue("C4_APPROVAL_SLIP"):
                    events.append(
                        {
                            "kind": "clue_unlocked",
                            "actor": "lu",
                            "target": "C4_APPROVAL_SLIP",
                            "zone": state.npcs[npc_id].zone,
                            "text": f"解锁线索：{scenario.clues['C4_APPROVAL_SLIP']['name']}",
                        }
                    )
            elif act == "PULL_BRAKE":
                neutralized.add(npc_id)
                npc = state.npcs[npc_id]
                npc.stats["panic"] = _clamp(npc.stats.get("panic", 0) - 20, 0, 100)
                events.append(
                    {
                        "kind": "intercepted",
                        "actor": "lu",
                        "target": npc_id,
                        "zone": npc.zone,
                        "text": f"{scenario.char_name(npc_id)}疯了似的扑向车头紧急制动拉环！陆建军一把死死攥住他的胳膊将其拽回：“敢动安全设备？找死吗！”",
                    }
                )
                for other in state.npcs.values():
                    other.add_memory(f"[{clock}] 陆建军在车头出手拦下了试图拉紧急制动的{scenario.char_name(npc_id)}。", limit=mem_limit)

    # 9.2 Non-movement actions & speeches
    brake_pulled = False
    for npc_id in ("chen", "lin", "lu", "zhou"):
        npc = state.npcs[npc_id]
        dec = decisions[npc_id]
        final = dec["final"]
        act = final["action"]
        tgt = final.get("target")
        speech = final.get("speech", "").strip()
        speech_to = final.get("speech_to", "player")

        if speech and not dec.get("skipped_llm"):
            # Deliver speech if player is in same zone or speech is public ("all")
            if npc.zone == state.player_zone or speech_to == "all":
                events.append(
                    {
                        "kind": "speech",
                        "actor": npc_id,
                        "target": speech_to,
                        "zone": npc.zone,
                        "text": f"{scenario.char_name(npc_id)}：“{speech}”",
                    }
                )
            # Record in same-zone listeners' memories
            for other_id, other in state.npcs.items():
                if other_id != npc_id and (other.zone == npc.zone or speech_to == "all"):
                    other.add_memory(f"[{clock}] {scenario.char_name(npc_id)}说：{speech}", limit=mem_limit)

        if npc_id in neutralized or dec["final_verdict"] != "PASS":
            continue

        if act == "HAND_OVER":
            events.append(
                {
                    "kind": "hand_over",
                    "actor": npc_id,
                    "target": "player",
                    "zone": npc.zone,
                    "text": "陈默颤抖着撕开左胸工装内袋，把沾满油污的《K14+200 检修记录本》和一枚背面刻满细字的旧工牌交到你手里。",
                }
            )
            for cid in ("C6_K14_HAZARD", "C7_BADGE_LAST_WORDS"):
                if state.unlock_clue(cid):
                    events.append(
                        {
                            "kind": "clue_unlocked",
                            "actor": npc_id,
                            "target": cid,
                            "zone": npc.zone,
                            "text": f"解锁线索：{scenario.clues[cid]['name']}",
                        }
                    )

        elif act == "CONFRONT":
            target_npc = state.npcs.get(str(tgt))
            if target_npc:
                # Avoid double-adding stats for forced confrontations already applied in Step 5/6
                is_already_counted = (
                    (npc_id == "lin" and tgt == "zhou" and lin_confronted_zhou)
                    or (npc_id == "lin" and tgt == "chen" and state.turn == 6 and dec["forced"])
                )
                if not is_already_counted:
                    _apply_capped_delta(target_npc, "panic", 20, start_stats, raw_deltas, cap)
                    _apply_capped_delta(target_npc, "guilt", 10, start_stats, raw_deltas, cap)
                events.append(
                    {
                        "kind": "confront",
                        "actor": npc_id,
                        "target": tgt,
                        "zone": npc.zone,
                        "text": f"{scenario.char_name(npc_id)}在{scenario.zone_name(npc.zone)}当众步步紧逼，厉声质问{scenario.char_name(str(tgt))}！",
                    }
                )

        elif act == "WHISPER":
            target_npc = state.npcs.get(str(tgt))
            if target_npc and target_npc.zone == npc.zone:
                whisper_msg = speech or "压低声音交换了几句隐秘的话"
                npc.add_memory(f"[{clock}] 你低声对{scenario.char_name(str(tgt))}说：{whisper_msg}", limit=mem_limit)
                target_npc.add_memory(f"[{clock}] {scenario.char_name(npc_id)}低声对你说：{whisper_msg}", limit=mem_limit)
                if state.player_zone == npc.zone and state.player_waited:
                    events.append(
                        {
                            "kind": "whisper_heard",
                            "actor": npc_id,
                            "target": tgt,
                            "zone": npc.zone,
                            "text": f"【偷听】{scenario.char_name(npc_id)}凑近{scenario.char_name(str(tgt))}低声说：“{whisper_msg}”",
                        }
                    )
                else:
                    events.append(
                        {
                            "kind": "whisper_seen",
                            "actor": npc_id,
                            "target": tgt,
                            "zone": npc.zone,
                            "text": f"{scenario.char_name(npc_id)}与{scenario.char_name(str(tgt))}在{scenario.zone_name(npc.zone)}凑在一起低声说着什么。",
                        }
                    )

        elif act == "HIDE_OR_DESTROY":
            item_id = str(tgt or "ITEM_APPROVAL_SLIP")
            if item_id in npc.items:
                npc.items.remove(item_id)
            state.flags["approval_slip_status"] = "DESTROYED"
            events.append(
                {
                    "kind": "destroy",
                    "actor": npc_id,
                    "target": item_id,
                    "zone": npc.zone,
                    "text": "趁车尾无人阻拦，周明远飞快撕碎公文包里的《免停运审批单》，将纸屑狠狠塞进检修垃圾箱深处！",
                }
            )

        elif act == "PULL_BRAKE":
            brake_pulled = True
            events.append(
                {
                    "kind": "brake",
                    "actor": npc_id,
                    "target": None,
                    "zone": npc.zone,
                    "text": f"{scenario.char_name(npc_id)}彻底失控，猛地拉下车头红色紧急制动拉环！刺耳的金属摩擦声撕裂整个隧道！",
                }
            )

    # 9.3 Movements in strict order: chen -> zhou -> lin -> lu
    for npc_id in scenario.world.get("move_order", ["chen", "zhou", "lin", "lu"]):
        npc = state.npcs[npc_id]
        if npc.detained or npc_id in neutralized:
            continue
        dec = decisions[npc_id]
        dest: str | None = None

        if dec["final"]["action"] == "MOVE" and dec["final_verdict"] == "PASS":
            dest = str(dec["final"]["target"])
        elif npc.tracking and npc.tracking in state.npcs:
            tracked_zone = state.npcs[npc.tracking].zone
            if tracked_zone != npc.zone:
                dest = tracked_zone

        if dest and dest in VALID_ZONES and dest != npc.zone:
            npc.zone = dest
            events.append(
                {
                    "kind": "move",
                    "actor": npc_id,
                    "target": dest,
                    "zone": dest,
                    "text": f"{scenario.char_name(npc_id)}移动到了{scenario.zone_name(dest)}。",
                }
            )

    # Record Inspector LogEntry for all 4 NPCs
    for npc_id, npc in state.npcs.items():
        dec = decisions[npc_id]
        delta_actual = {
            k: npc.stats[k] - start_stats[npc_id][k]
            for k in npc.stats
            if npc.stats[k] != start_stats[npc_id][k]
        }
        state.log.append(
            LogEntry(
                turn=state.turn,
                clock=clock,
                npc=npc_id,
                tags_hit=npc_tags_hit[npc_id],
                delta=delta_actual,
                stats_after=dict(npc.stats),
                thought=dec["final"].get("thought", ""),
                speech=dec["final"].get("speech", ""),
                proposed=dec["proposed"],
                verdict=dec["verdict"],
                reason=dec["reason"],
                retry=dec["retry"],
                forced=dec["forced"],
                llm_ms=dec["llm_ms"],
                json_repaired=dec["json_repaired"],
                skipped_llm=bool(dec.get("skipped_llm")),
            )
        )

    # ── Step 10: End-of-turn resolution ──
    if brake_pulled:
        state.record_ending("A")
        events.append(
            {
                "kind": "loop_reset",
                "actor": None,
                "target": None,
                "zone": None,
                "text": scenario.endings["A"]["narration"],
            }
        )
        reset_loop(state, scenario, skip_to_t2=False, increment_loop=True)
        return events

    max_turns = int(scenario.world["max_turns"])
    if state.turn >= max_turns:
        required_clues = set(scenario.world["puzzle_solution"].values())
        if (
            not state.puzzle_solved
            and not force_resolve_t8
            and required_clues.issubset(set(state.clues_unlocked))
        ):
            # Anti-frustration safeguard: player unlocked C4 right on T8! Let them complete puzzle before 00:00.
            state.flags["awaiting_final_puzzle"] = True
            events.append(
                {
                    "kind": "final_puzzle_prompt",
                    "actor": "player",
                    "target": None,
                    "zone": state.player_zone,
                    "text": "23:59 最后十秒！你已集齐全部四张核心真相牌，请在时钟跳向 00:00 前完成真相拼图！",
                }
            )
            return events

        midnight_events = await finalize_midnight(state, scenario, llm, user_token=user_token)
        events.extend(midnight_events)
        return events

    # Advance to next turn
    state.turn += 1
    if state.turn == 2 and not state.flags.get("t2_earphone_done"):
        ear = scenario.timeline["earphone_t2"]
        events.append(
            {
                "kind": "earphone",
                "actor": "player",
                "target": None,
                "zone": state.player_zone,
                "text": f"{ear['scene']}\n{ear['voice']}",
            }
        )
        state.flags["t2_earphone_done"] = True
        if state.unlock_clue("C0_EARPHONE_ECHO"):
            events.append(
                {
                    "kind": "clue_unlocked",
                    "actor": "player",
                    "target": "C0_EARPHONE_ECHO",
                    "zone": state.player_zone,
                    "text": f"解锁线索：{scenario.clues['C0_EARPHONE_ECHO']['name']}",
                }
            )

    return events
