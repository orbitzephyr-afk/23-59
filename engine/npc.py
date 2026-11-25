from __future__ import annotations

import json
import re
from typing import Any

from .llm import LLMClient
from .rules import get_allowed_actions, validate_action
from .scenario import ScenarioData
from .state import GameState, NPCState


VALID_SPEECH_TO = {"player", "zhou", "chen", "lin", "lu", "all", "none"}


def _extract_json(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first == -1 or last == -1 or last < first:
        return None
    try:
        parsed = json.loads(cleaned[first : last + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _next_fallback_line(npc: NPCState, scenario: ScenarioData) -> str:
    lines = scenario.characters[npc.id].get("fallback_lines") or ["……"]
    line = lines[npc.fallback_cursor % len(lines)]
    npc.fallback_cursor += 1
    return line


def _build_npc_system_prompt(
    state: GameState,
    npc: NPCState,
    scenario: ScenarioData,
    allowed_actions: list[str],
    retry_hint: str = "",
    forced_hint: str = "",
) -> str:
    cfg = scenario.characters[npc.id]
    disclosable = scenario.get_disclosable(
        npc.id, npc.stats, npc.detained, state.flags, state.clues_unlocked
    )
    state_words, _ = scenario.get_state_words_and_mood(
        npc.id, npc.stats, npc.detained, state.flags, state.clues_unlocked
    )

    others: list[str] = []
    if state.player_zone == npc.zone:
        others.append("乘客(player)")
    for other_id, other in state.npcs.items():
        if other_id != npc.id and other.zone == npc.zone:
            others.append(f"{scenario.char_name(other_id)}({other_id})")

    memory_block = "\n".join(f"- {m}" for m in npc.memory) if npc.memory else "- 暂无特别记忆。"
    secret_text = cfg["secret"] if cfg.get("secret") else "无（你是中立下班民警，没有隐瞒秘密）"

    return scenario.npc_prompt_template.format(
        name=cfg["name"],
        role=cfg.get("role", ""),
        persona=cfg["persona"],
        cover_story=cfg["cover_story"],
        secret=secret_text,
        disclosable=disclosable,
        state_words=state_words,
        zone=npc.zone,
        zone_name=scenario.zone_name(npc.zone),
        others="、".join(others) if others else "暂无其他人",
        memory=memory_block,
        allowed_actions=", ".join(allowed_actions),
        retry_hint=f"{retry_hint}\n" if retry_hint else "",
        forced_hint=f"{forced_hint}\n" if forced_hint else "",
        speech_style=cfg["speech_style"],
    )


def _mock_decision(
    state: GameState,
    npc: NPCState,
    scenario: ScenarioData,
    allowed_actions: list[str],
    retry_reason: str = "",
) -> dict[str, Any]:
    """Deterministic, in-character mock decision that exercises all rule-engine branches cleanly."""
    if npc.forced_action:
        act = npc.forced_action["action"]
        tgt = npc.forced_action.get("target")
        forced_speeches = {
            ("chen", "HAND_OVER"): ("压了半年我实在撑不住了……这是师父的记录本和旧工牌，求你救救明早那班车！", "不能再躲了，对不起师父……"),
            ("lin", "CONFRONT"): ("周明远！把你包里的《免停运审批单》拿出来，录音笔开着呢！", "绝对不能让他再装体面了。"),
            ("lu", "DETAIN"): ("别动！市局便衣，这是警官证。周明远，请你配合把公文包交出来接受调查。", "人证物证齐全，立刻控场。"),
            ("zhou", "MOVE"): ("车尾仪表好像有点异响，我去看看。", "得赶紧去车尾稳住陈默。"),
            ("lin", "MOVE"): ("我去车尾透透气。", "去堵住他。"),
        }
        speech, thought = forced_speeches.get(
            (npc.id, act), (_next_fallback_line(npc, scenario), f"按计划执行 {act}。")
        )
        return {
            "thought": thought,
            "speech": speech,
            "speech_to": "all" if act in ("CONFRONT", "DETAIN") else "player",
            "action": act,
            "target": tgt,
        }

    # Retry after rule rejection (e.g. zhou rejected trying to destroy in FRONT -> MOVE REAR!)
    if retry_reason:
        if npc.id == "zhou" and "车尾" in retry_reason and npc.zone != "REAR":
            return {
                "thought": "这节车厢没法动手，必须先找借口去车尾垃圾箱毁掉审批单！",
                "speech": "这里太闷，我去车尾接个电话。",
                "speech_to": "all",
                "action": "MOVE",
                "target": "REAR",
            }
        if npc.id == "zhou" and "车头" in retry_reason and npc.zone != "FRONT":
            return {
                "thought": "紧急拉环在车头，我得冲去车头拉闸下车！",
                "speech": "让开！这破车出故障了！",
                "speech_to": "all",
                "action": "MOVE",
                "target": "FRONT",
            }
        return {
            "thought": "算了，先按兵不动观察局势。",
            "speech": _next_fallback_line(npc, scenario),
            "speech_to": "player",
            "action": "STAY",
            "target": None,
        }

    # Normal mock behavior driven by stats
    if npc.id == "zhou":
        panic = npc.stats.get("panic", 0)
        if panic >= 90 and "PULL_BRAKE" in allowed_actions:
            return {
                "thought": "彻底瞒不住了！拉下紧急制动强行开门跑！",
                "speech": "都别拦我！这车马上要出事了！",
                "speech_to": "all",
                "action": "PULL_BRAKE",
                "target": None,
            }
        if panic >= 65 and "HIDE_OR_DESTROY" in allowed_actions:
            return {
                "thought": "绝对不能让审批单落进他们手里，必须立刻销毁！",
                "speech": "一派胡言，我没工夫听你胡扯！",
                "speech_to": "player",
                "action": "HIDE_OR_DESTROY",
                "target": "ITEM_APPROVAL_SLIP",
            }

    if npc.id == "chen":
        if state.flags.get("logbook_handed"):
            return {
                "thought": "师父的冤屈终于能洗清了，我要指证周明远。",
                "speech": "记录本和旧工牌都已经交出去了，周副总，你别再骗人了！",
                "speech_to": "all",
                "action": "STAY",
                "target": None,
            }
        if npc.stats.get("guard", 60) <= 35:
            return {
                "thought": "我快撑不住了……难道真的该把本子交出去吗？",
                "speech": "真不是师父忘拉闸……可我妈刚做完心脏手术，我实在没办法……",
                "speech_to": "player",
                "action": "STAY",
                "target": None,
            }

    if npc.id == "lin":
        if state.flags.get("lin_forgave") and state.flags.get("lin_target") != "zhou":
            return {
                "thought": "原来爸临走前还在惦记我，陈默也不是凶手……那匿名信到底是谁寄的？",
                "speech": "我错怪陈默了……那当年压下报告、寄匿名信骗我的人到底是谁？",
                "speech_to": "player",
                "action": "STAY",
                "target": None,
            }
        if "C5_LIN_IDENTITY" in state.clues_unlocked or npc.stats.get("guard", 65) <= 45:
            return {
                "thought": "他居然知道我爸的事，不能全盘托出，但可以探探他手里有什么。",
                "speech": "没错，我就是赵岚。上周有人寄给我半页问询表，我要弄清楚我爸到底怎么死的。",
                "speech_to": "player",
                "action": "STAY",
                "target": None,
            }

    if npc.id == "lu":
        if state.flags.get("lu_active"):
            return {
                "thought": "物证确凿，盯死周明远，别让他毁证或动紧急制动。",
                "speech": "市局便衣，现场我接管了。都冷静，谁也别乱动。",
                "speech_to": "all",
                "action": "STAY",
                "target": None,
            }
        if npc.stats.get("resolve", 0) >= 45:
            return {
                "thought": "话听起来有点门道，但没有硬物证我不能瞎亮证。",
                "speech": "你说的这些我都听见了，但口说无凭——把实打实的物证拿出来。",
                "speech_to": "player",
                "action": "STAY",
                "target": None,
            }

    return {
        "thought": "先敷衍过去，别暴露太多。",
        "speech": _next_fallback_line(npc, scenario),
        "speech_to": "player",
        "action": "STAY",
        "target": None,
    }


def _normalize_decision(
    parsed: dict[str, Any],
    npc: NPCState,
    allowed_actions: list[str],
) -> dict[str, Any] | None:
    if not isinstance(parsed, dict):
        return None
    if "action" not in parsed or "speech" not in parsed:
        return None
    action = str(parsed.get("action") or "").upper().strip()
    if npc.forced_action:
        action = npc.forced_action["action"]
        target = npc.forced_action.get("target")
    else:
        if action not in allowed_actions:
            return None
        target = parsed.get("target")
        if target in ("", "null", "None"):
            target = None

    speech_to = str(parsed.get("speech_to") or "player").lower().strip()
    if speech_to not in VALID_SPEECH_TO:
        speech_to = "player"

    speech = str(parsed.get("speech") or "").strip()[:80]
    thought = str(parsed.get("thought") or "").strip()[:120]

    return {
        "thought": thought,
        "speech": speech,
        "speech_to": speech_to,
        "action": action,
        "target": target,
    }


async def _call_llm_once(
    state: GameState,
    npc: NPCState,
    scenario: ScenarioData,
    llm: LLMClient,
    user_prompt: str,
    allowed_actions: list[str],
    *,
    user_token: str | None = None,
    retry_hint: str = "",
    forced_hint: str = "",
) -> tuple[dict[str, Any], int, bool]:
    """Call LLM (or mock), parse JSON, retry once on malformed JSON, degrade safely on failure."""
    if llm.is_mock(user_token) and llm.mock_override is None:
        return _mock_decision(state, npc, scenario, allowed_actions, retry_reason=retry_hint), 15, False

    sys_prompt = _build_npc_system_prompt(
        state, npc, scenario, allowed_actions, retry_hint=retry_hint, forced_hint=forced_hint
    )

    total_ms = 0
    repaired = False
    cur_user_prompt = user_prompt

    for attempt in range(2):
        try:
            raw, ms = await llm.complete(
                sys_prompt,
                cur_user_prompt,
                role_kind="npc",
                npc_id=npc.id,
                user_token=user_token,
                temperature=0.7,
                max_tokens=300,
            )
            total_ms += ms
            parsed = _extract_json(raw)
            norm = _normalize_decision(parsed, npc, allowed_actions) if parsed else None
            if norm is not None:
                return norm, total_ms, (attempt > 0)
            repaired = True
            cur_user_prompt = (
                f"{user_prompt}\n\n【格式纠正】你上次的输出不是合法 JSON 或 action 不在可选列表中。"
                f"请严格只输出包含 thought/speech/speech_to/action/target 的单个 JSON 对象。"
            )
        except Exception:
            repaired = True
            break

    # Safe fallback: never crash the game!
    fallback_action = npc.forced_action["action"] if npc.forced_action else "STAY"
    fallback_target = npc.forced_action.get("target") if npc.forced_action else None
    return (
        {
            "thought": "（模型响应异常，安全降级为保持原状）",
            "speech": _next_fallback_line(npc, scenario),
            "speech_to": "player",
            "action": fallback_action,
            "target": fallback_target,
        },
        total_ms,
        True,
    )


async def decide_for_npc(
    state: GameState,
    npc: NPCState,
    scenario: ScenarioData,
    llm: LLMClient,
    user_prompt: str,
    *,
    user_token: str | None = None,
) -> dict[str, Any]:
    """Run full decide -> rule-validate -> max-1-retry loop for a single NPC."""
    allowed = get_allowed_actions(state, npc, scenario)
    is_forced = npc.forced_action is not None
    forced_hint = ""
    if is_forced:
        forced_hint = (
            f"你本回合已决定执行 {npc.forced_action['action']}"
            f"（目标：{npc.forced_action.get('target')}），只需写贴合当前心态的台词和心理活动。"
        )
        if npc.forced_action["action"] not in allowed:
            allowed = allowed + [npc.forced_action["action"]]

    first_decision, ms1, repaired1 = await _call_llm_once(
        state,
        npc,
        scenario,
        llm,
        user_prompt,
        allowed,
        user_token=user_token,
        forced_hint=forced_hint,
    )

    verdict, reason = validate_action(state, npc, first_decision, scenario, forced=is_forced)

    result: dict[str, Any] = {
        "proposed": {"action": first_decision["action"], "target": first_decision.get("target")},
        "verdict": verdict,
        "reason": reason,
        "retry": None,
        "final": first_decision,
        "final_verdict": verdict,
        "final_reason": reason,
        "llm_ms": ms1,
        "json_repaired": repaired1,
        "forced": is_forced,
    }

    if verdict == "REJECTED" and not is_forced:
        retry_hint = (
            f"你刚才想执行 {first_decision['action']}（目标：{first_decision.get('target')}），"
            f"但被规则驳回：{reason}。请立刻重新选择一个合法动作。"
        )
        second_decision, ms2, repaired2 = await _call_llm_once(
            state,
            npc,
            scenario,
            llm,
            user_prompt,
            allowed,
            user_token=user_token,
            retry_hint=retry_hint,
        )
        v2, r2 = validate_action(state, npc, second_decision, scenario, forced=False)
        result["llm_ms"] += ms2
        result["json_repaired"] = result["json_repaired"] or repaired2

        if v2 == "REJECTED":
            second_decision["action"] = "STAY"
            second_decision["target"] = None
            v2, r2 = "PASS", f"二次校验仍被驳回({r2})，降级为 STAY"

        result["retry"] = {
            "action": second_decision["action"],
            "target": second_decision.get("target"),
            "verdict": v2,
            "reason": r2,
        }
        result["final"] = second_decision
        result["final_verdict"] = v2
        result["final_reason"] = r2

    return result
