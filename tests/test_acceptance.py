from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["LLM_MOCK"] = "1"

import app as web_app
from engine.endings import evaluate_puzzle
from engine.llm import LLMClient
from engine.scenario import load_scenario
from engine.state import create_new_game, reset_loop
from engine.turn import finalize_midnight, process_turn


@pytest.fixture
def scenario():
    return load_scenario(force_reload=True)


@pytest.fixture
def llm():
    client = LLMClient()
    return client


def _run(coro):
    return asyncio.run(coro)


# ── Test 1: 真结局一轮通关（第 3 轮路线）──
def test_01_true_ending_loop3_route(scenario, llm):
    state = create_new_game(scenario)
    # Simulate entering Loop 3 via skip_to_t2 with C0, C3, C6, C7 unlocked and puzzle slots 2..4 filled
    state.clues_unlocked = [
        "C1_OFFICIAL_LIE",
        "C0_EARPHONE_ECHO",
        "C3_WHISPER_BRIBE",
        "C6_K14_HAZARD",
        "C7_BADGE_LAST_WORDS",
    ]
    state.loop_count = 2
    reset_loop(state, scenario, skip_to_t2=True, increment_loop=True)
    evaluate_puzzle(
        state,
        {"1": None, "2": "C3_WHISPER_BRIBE", "3": "C7_BADGE_LAST_WORDS", "4": "C6_K14_HAZARD"},
        scenario,
    )
    assert state.turn == 2

    # T2: move REAR, present C3 to chen -> guard 30, guilt 70
    _run(process_turn(state, "REAR", {"type": "SPEAK_PRIVATE", "target": "chen", "text": "", "clue_id": "C3_WHISPER_BRIBE"}, scenario, llm))
    assert state.npcs["chen"].stats["guard"] == 30
    assert state.npcs["chen"].stats["guilt"] == 70

    # T3: present C7 to chen -> guard 15, guilt 90 -> HAND_OVER ITEM_LOGBOOK; zhou moves REAR
    _run(process_turn(state, None, {"type": "SPEAK_PRIVATE", "target": "chen", "text": "", "clue_id": "C7_BADGE_LAST_WORDS"}, scenario, llm))
    assert state.flags["logbook_handed"] is True
    assert "ITEM_LOGBOOK" in state.player_items
    assert state.npcs["zhou"].zone == "REAR"

    # T4: move MID, present C6 (physical!) to lu -> resolve 70 -> lu_active -> follows zhou to REAR
    _run(process_turn(state, "MID", {"type": "SPEAK_PRIVATE", "target": "lu", "text": "这是记录本实物", "clue_id": "C6_K14_HAZARD"}, scenario, llm))
    assert state.npcs["lu"].stats["resolve"] >= 70
    assert state.flags["lu_active"] is True
    assert state.npcs["lu"].zone == "REAR"

    # T5: present C7 to lin and mention 10万封口 -> lin_forgave & lin_target=zhou; zhou->FRONT, lin&lu follow->FRONT
    _run(process_turn(state, None, {"type": "SPEAK_PRIVATE", "target": "lin", "text": "周明远拿10万封口费逼小陈签伪证", "clue_id": "C7_BADGE_LAST_WORDS"}, scenario, llm))
    assert state.flags["lin_forgave"] is True
    assert state.flags["lin_target"] == "zhou"
    assert state.npcs["zhou"].zone == "FRONT"
    assert state.npcs["lin"].zone == "FRONT"
    assert state.npcs["lu"].zone == "FRONT"

    # T6: move FRONT, speak public about 审批单; lin confronts zhou -> zhou panic 55 (capped)
    _run(process_turn(state, "FRONT", {"type": "SPEAK_PUBLIC", "text": "周副总，你包里的免停运审批单还要藏吗？"}, scenario, llm))
    assert state.npcs["zhou"].stats["panic"] == 55

    # T7: speak public about K14+200 and 明早首班车 -> zhou panic 85 >= 75 -> lu DETAIN same turn -> C4 unlocked & SECURED
    _run(process_turn(state, None, {"type": "SPEAK_PUBLIC", "text": "K14+200 绝缘值 0.3MΩ，明早首班车必出事！"}, scenario, llm))
    assert state.npcs["zhou"].stats["panic"] == 85
    assert state.npcs["zhou"].detained is True
    assert state.flags["approval_slip_status"] == "SECURED"
    assert "C4_APPROVAL_SLIP" in state.clues_unlocked

    # T8: place C4 into puzzle slot 1 -> puzzle_solved -> WAIT -> Ending D (bright)
    solved, _ = evaluate_puzzle(
        state,
        {
            "1": "C4_APPROVAL_SLIP",
            "2": "C3_WHISPER_BRIBE",
            "3": "C7_BADGE_LAST_WORDS",
            "4": "C6_K14_HAZARD",
        },
        scenario,
    )
    assert solved is True
    events = _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))
    assert state.ending is not None
    assert state.ending["id"] == "D"
    assert state.ending["visual"] == "bright"
    assert any(e["kind"] == "midnight" for e in events)


# ── Test 2: 第 2 轮取牌（解锁 C3、C6、C7）──
def test_02_loop2_clue_harvest(scenario, llm):
    state = create_new_game(scenario)
    state.unlock_clue("C0_EARPHONE_ECHO")
    reset_loop(state, scenario, skip_to_t2=True, increment_loop=True)

    # T2: move REAR, present C0 & say 师父喊你快跑 -> chen guard 45, guilt 85
    _run(process_turn(state, "REAR", {"type": "SPEAK_PRIVATE", "target": "chen", "text": "老赵喊你快跑", "clue_id": "C0_EARPHONE_ECHO"}, scenario, llm))
    assert state.npcs["chen"].stats["guard"] == 45
    assert state.npcs["chen"].stats["guilt"] == 85

    # T3: WAIT -> zhou moves to REAR
    _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))
    assert state.npcs["zhou"].zone == "REAR"

    # T4: WAIT (装睡) -> T4 whisper heard -> C3 unlocked
    _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))
    assert "C3_WHISPER_BRIBE" in state.clues_unlocked

    # T5: present C3 to chen -> guard 15, guilt 100 -> HAND_OVER -> C6 & C7 unlocked
    _run(process_turn(state, None, {"type": "SPEAK_PRIVATE", "target": "chen", "text": "", "clue_id": "C3_WHISPER_BRIBE"}, scenario, llm))
    assert state.npcs["chen"].stats["guard"] == 15
    assert state.npcs["chen"].stats["guilt"] == 100
    assert "C6_K14_HAZARD" in state.clues_unlocked
    assert "C7_BADGE_LAST_WORDS" in state.clues_unlocked

    # T6-T8: WAIT -> loop reset (missing C4), clues preserved
    for _ in range(3):
        _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))
    assert {"C3_WHISPER_BRIBE", "C6_K14_HAZARD", "C7_BADGE_LAST_WORDS"}.issubset(set(state.clues_unlocked))


# ── Test 3: 毁证被驳回再重决策（FRONT -> REJECTED -> MOVE REAR）──
def test_03_destroy_rejected_then_retry_move_rear(scenario, llm):
    state = create_new_game(scenario)
    state.npcs["zhou"].zone = "FRONT"
    state.npcs["zhou"].stats["panic"] = 70
    state.player_zone = "FRONT"

    _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))
    zhou_logs = [entry for entry in state.log if entry.npc == "zhou"]
    assert len(zhou_logs) == 1
    entry = zhou_logs[0]
    assert entry.proposed["action"] == "HIDE_OR_DESTROY"
    assert entry.verdict == "REJECTED"
    assert "车尾" in entry.reason
    assert entry.retry is not None
    assert entry.retry["action"] == "MOVE"
    assert entry.retry["target"] == "REAR"
    assert entry.retry["verdict"] == "PASS"
    assert state.npcs["zhou"].zone == "REAR"


# ── Test 4: 老陆未亮证时周在 REAR 照样能毁证 -> 结局 B ──
def test_04_unactivated_lu_allows_destroy_then_ending_b(scenario, llm):
    state = create_new_game(scenario)
    state.turn = 8
    state.npcs["zhou"].zone = "REAR"
    state.npcs["zhou"].stats["panic"] = 70
    state.npcs["lu"].zone = "REAR"
    state.flags["lu_active"] = False
    # Unlock all 4 clues and solve puzzle
    for cid in ("C3_WHISPER_BRIBE", "C4_APPROVAL_SLIP", "C6_K14_HAZARD", "C7_BADGE_LAST_WORDS"):
        state.unlock_clue(cid)
    evaluate_puzzle(
        state,
        {
            "1": "C4_APPROVAL_SLIP",
            "2": "C3_WHISPER_BRIBE",
            "3": "C7_BADGE_LAST_WORDS",
            "4": "C6_K14_HAZARD",
        },
        scenario,
    )
    assert state.puzzle_solved is True

    _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))
    assert state.flags["approval_slip_status"] == "DESTROYED"
    assert state.ending is not None
    assert state.ending["id"] == "B"
    assert state.ending["visual"] == "dim"


# ── Test 5: 公共安全例外（老陆未亮证但在 FRONT 拦下拉闸）──
def test_05_public_safety_brake_intercept(scenario, llm):
    state = create_new_game(scenario)
    state.npcs["zhou"].zone = "FRONT"
    state.npcs["zhou"].stats["panic"] = 95
    state.npcs["lu"].zone = "FRONT"
    state.flags["lu_active"] = False
    loop_before = state.loop_count

    events = _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))
    assert any(e["kind"] == "intercepted" for e in events)
    assert not any(e["kind"] == "loop_reset" for e in events)
    assert state.loop_count == loop_before
    assert state.npcs["zhou"].stats["panic"] == 75  # 95 - 20


# ── Test 6: 只靠嘴过不了线（老陆传闻上限 45，未亮证）──
def test_06_lu_hearsay_capped_at_45(scenario, llm):
    state = create_new_game(scenario)
    # Mention all 5 tags that add resolve to lu over turns
    utterances = [
        "林岚是老赵的女儿",
        "老赵临终喊快跑",
        "周明远拿10万封口费逼陈默签伪证",
        "周明远藏着免停运审批单",
        "K14+200 绝缘老化明早首班车会出事",
    ]
    for msg in utterances:
        _run(process_turn(state, None, {"type": "SPEAK_PRIVATE", "target": "lu", "text": msg}, scenario, llm))
    assert state.npcs["lu"].stats["resolve"] == 45
    assert state.flags["lu_active"] is False


# ── Test 7: 装睡偷听 vs 清醒说话取消密谈 ──
def test_07_t4_whisper_sleep_vs_awake(scenario, llm):
    # Branch A: sleep in REAR at T4 -> unlock C3
    s1 = create_new_game(scenario)
    _run(process_turn(s1, "REAR", {"type": "WAIT"}, scenario, llm))  # T1
    _run(process_turn(s1, None, {"type": "WAIT"}, scenario, llm))    # T2
    _run(process_turn(s1, None, {"type": "WAIT"}, scenario, llm))    # T3 (zhou moves REAR)
    ev1 = _run(process_turn(s1, None, {"type": "WAIT"}, scenario, llm))  # T4
    assert "C3_WHISPER_BRIBE" in s1.clues_unlocked
    assert any(e["kind"] == "whisper_heard" for e in ev1)

    # Branch B: speak in REAR at T4 (not WAIT) -> cancelled, no C3
    s2 = create_new_game(scenario)
    _run(process_turn(s2, "REAR", {"type": "WAIT"}, scenario, llm))  # T1
    _run(process_turn(s2, None, {"type": "WAIT"}, scenario, llm))    # T2
    _run(process_turn(s2, None, {"type": "WAIT"}, scenario, llm))    # T3
    _run(process_turn(s2, None, {"type": "SPEAK_PRIVATE", "target": "chen", "text": "你们在聊什么？"}, scenario, llm))  # T4
    assert "C3_WHISPER_BRIBE" not in s2.clues_unlocked
    assert s2.flags["t4_whisper_done"] is False


# ── Test 8: 单回合数值封顶 ±30 ──
def test_08_per_turn_stat_cap_30(scenario, llm):
    state = create_new_game(scenario)
    before = state.npcs["zhou"].stats["panic"]
    # Hits TAG_BRIBE_10W (+35) AND TAG_APPROVAL_SLIP (+40) in one turn -> total +75 capped to +30!
    _run(
        process_turn(
            state,
            "FRONT",
            {"type": "SPEAK_PRIVATE", "target": "zhou", "text": "你拿10万封口费逼签伪证，还藏着免停运审批单！"},
            scenario,
            llm,
        )
    )
    assert state.npcs["zhou"].stats["panic"] - before == 30


# ── Test 9: 无人干预的第一轮（连续 8 次 WAIT）──
def test_09_passive_loop1_timeline(scenario, llm):
    state = create_new_game(scenario)
    _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))  # T1 -> T2 (C0 unlocked)
    assert "C0_EARPHONE_ECHO" in state.clues_unlocked
    _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))  # T2
    _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))  # T3 -> zhou moves REAR
    assert state.npcs["zhou"].zone == "REAR"
    _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))  # T4 -> whisper_seen
    assert state.flags["t4_whisper_done"] is True
    assert "C3_WHISPER_BRIBE" not in state.clues_unlocked
    _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))  # T5 -> zhou FRONT, lin REAR
    assert state.npcs["zhou"].zone == "FRONT"
    assert state.npcs["lin"].zone == "REAR"
    ev6 = _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))  # T6 -> lin confronts chen
    assert any(e["kind"] == "confront" and e["actor"] == "lin" and e["target"] == "chen" for e in ev6)
    _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))  # T7
    ev8 = _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))  # T8 -> reset!
    assert any(e["kind"] == "loop_reset" for e in ev8)
    assert state.loop_count == 2
    assert state.turn == 1
    assert "C0_EARPHONE_ECHO" in state.clues_unlocked
    assert "C1_OFFICIAL_LIE" in state.clues_unlocked


# ── Test 10: 模型全挂（非法 JSON 或超时）安全降级 STAY ──
def test_10_llm_broken_json_and_timeout_fallback(scenario):
    bad_llm = LLMClient()
    bad_llm.mock_override = lambda role_kind, npc_id, prompt: "THIS IS NOT JSON AT ALL {"
    state = create_new_game(scenario)
    _run(process_turn(state, None, {"type": "SPEAK_PRIVATE", "target": "lin", "text": "你好"}, scenario, bad_llm))
    lin_log = [e for e in state.log if e.npc == "lin"][0]
    assert lin_log.json_repaired is True
    assert lin_log.proposed["action"] == "STAY"
    assert state.turn == 2

    async def _timeout_fn(role_kind, npc_id, prompt):
        raise TimeoutError("simulated timeout")

    timeout_llm = LLMClient()
    timeout_llm.mock_override = _timeout_fn
    _run(process_turn(state, None, {"type": "SPEAK_PRIVATE", "target": "lin", "text": "再试试"}, scenario, timeout_llm))
    lin_log2 = [e for e in state.log if e.npc == "lin"][-1]
    assert lin_log2.json_repaired is True
    assert lin_log2.proposed["action"] == "STAY"
    assert state.turn == 3


# ── Test 11: 只拼图不行动 -> 结局 B，不是 D ──
def test_11_puzzle_only_without_action_gives_ending_b(scenario, llm):
    state = create_new_game(scenario)
    for cid in ("C3_WHISPER_BRIBE", "C4_APPROVAL_SLIP", "C6_K14_HAZARD", "C7_BADGE_LAST_WORDS"):
        state.unlock_clue(cid)
    solved, _ = evaluate_puzzle(
        state,
        {
            "1": "C4_APPROVAL_SLIP",
            "2": "C3_WHISPER_BRIBE",
            "3": "C7_BADGE_LAST_WORDS",
            "4": "C6_K14_HAZARD",
        },
        scenario,
    )
    assert solved is True
    for _ in range(8):
        _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))
    assert state.ending is not None
    assert state.ending["id"] == "B"


# ── Extra Test 12: 硬核结局 C（抓周但林岚未释怀）──
def test_12_ending_c_justice_without_forgiveness(scenario, llm):
    state = create_new_game(scenario)
    state.turn = 8
    for cid in ("C3_WHISPER_BRIBE", "C4_APPROVAL_SLIP", "C6_K14_HAZARD", "C7_BADGE_LAST_WORDS"):
        state.unlock_clue(cid)
    evaluate_puzzle(
        state,
        {
            "1": "C4_APPROVAL_SLIP",
            "2": "C3_WHISPER_BRIBE",
            "3": "C7_BADGE_LAST_WORDS",
            "4": "C6_K14_HAZARD",
        },
        scenario,
    )
    state.flags["approval_slip_status"] = "SECURED"
    state.flags["logbook_handed"] = True
    state.flags["lin_forgave"] = False

    _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))
    assert state.ending is not None
    assert state.ending["id"] == "C"
    assert state.ending["visual"] == "normal"


# ── Extra Test 13: 老陆亮证在 REAR 拦截周毁证 -> INTERCEPTED + 解锁 C4 ──
def test_13_activated_lu_intercepts_destroy_in_rear(scenario, llm):
    state = create_new_game(scenario)
    state.npcs["zhou"].zone = "REAR"
    state.npcs["zhou"].stats["panic"] = 70
    state.npcs["lu"].zone = "REAR"
    state.flags["lu_active"] = True

    events = _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))
    assert any(e["kind"] == "intercepted" for e in events)
    assert state.flags["approval_slip_status"] == "SECURED"
    assert state.npcs["zhou"].detained is True
    assert "C4_APPROVAL_SLIP" in state.clues_unlocked


# ── Extra Test 14: T8 刚拿到 C4 触发终局拼图确认弹窗，拼完进结局 D ──
def test_14_t8_last_second_puzzle_safeguard(scenario, llm):
    state = create_new_game(scenario)
    state.turn = 8
    for cid in ("C3_WHISPER_BRIBE", "C4_APPROVAL_SLIP", "C6_K14_HAZARD", "C7_BADGE_LAST_WORDS"):
        state.unlock_clue(cid)
    state.flags["approval_slip_status"] = "SECURED"
    state.flags["logbook_handed"] = True
    state.flags["lin_forgave"] = True
    # Puzzle NOT solved yet at T8 end!
    ev = _run(process_turn(state, None, {"type": "WAIT"}, scenario, llm))
    assert state.flags["awaiting_final_puzzle"] is True
    assert state.ending is None
    assert any(e["kind"] == "final_puzzle_prompt" for e in ev)

    # Now player finishes puzzle and finalizes -> Ending D!
    solved, _ = evaluate_puzzle(
        state,
        {
            "1": "C4_APPROVAL_SLIP",
            "2": "C3_WHISPER_BRIBE",
            "3": "C7_BADGE_LAST_WORDS",
            "4": "C6_K14_HAZARD",
        },
        scenario,
    )
    assert solved is True
    _run(finalize_midnight(state, scenario, llm))
    assert state.ending is not None
    assert state.ending["id"] == "D"


# ── Extra Test 15: 剧本数据规范 & 林岚防凭空剧透检查 ──
def test_15_scenario_content_constraints_and_no_spoiler(scenario):
    assert len(scenario.clues) == 8
    for cid, c in scenario.clues.items():
        assert len(c["text"]) <= 60, f"{cid} too long: {len(c['text'])}"

    assert len(scenario.tags) == 7
    for tid, t in scenario.tags.items():
        assert 5 <= len(t["keywords"]) <= 10, f"{tid} kw count={len(t['keywords'])}"

    for eid in ("B", "C", "D"):
        assert len(scenario.endings[eid]["narration"]) <= 150

    for cid, char in scenario.characters.items():
        assert len(char["fallback_lines"]) == 5

    # Lin forgave without knowing Zhou must NOT leak Zhou
    dis = scenario.get_disclosable(
        "lin",
        {"guard": 35, "guilt": 25, "panic": 30},
        False,
        {"lin_forgave": True, "lin_target": None},
        ["C7_BADGE_LAST_WORDS"],
    )
    assert "绝不要凭空点名怀疑周明远" in dis


# ── Extra Test 16: FastAPI HTTP 契约测试 ──
def test_16_fastapi_http_contract():
    client = TestClient(web_app.app)
    r_index = client.get("/")
    assert r_index.status_code == 200
    assert "《23:59》" in r_index.text

    r_health = client.get("/api/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "ok"

    r_sess = client.post("/api/session", json={})
    assert r_sess.status_code == 200
    sid = r_sess.json()["session_id"]
    assert r_sess.json()["view"]["clock"] == "23:52"

    # Illegal private speak to different zone (zhou is in FRONT, player in MID) -> 400 and turn unchanged!
    r_bad = client.post(
        "/api/turn",
        json={"session_id": sid, "move": None, "action": {"type": "SPEAK_PRIVATE", "target": "zhou", "text": "喂"}},
    )
    assert r_bad.status_code == 400
    r_state = client.get(f"/api/state?session_id={sid}")
    assert r_state.json()["view"]["turn"] == 1

    # Valid OBSERVE(lin) unlocks C2_HALF_TESTIMONY
    r_obs = client.post(
        "/api/turn",
        json={"session_id": sid, "move": None, "action": {"type": "OBSERVE", "target": "lin"}},
    )
    assert r_obs.status_code == 200
    clue_ids = [c["id"] for c in r_obs.json()["view"]["clues"]]
    assert "C2_HALF_TESTIMONY" in clue_ids
    assert "C0_EARPHONE_ECHO" in clue_ids  # T1->T2 automatically triggers earphone!
