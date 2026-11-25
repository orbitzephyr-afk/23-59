from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine.endings import evaluate_puzzle
from engine.llm import LLMClient
from engine.scenario import load_scenario
from engine.state import GameState, build_inspector, build_view, create_new_game, reset_loop
from engine.turn import TurnInputError, finalize_midnight, process_turn


ROOT_DIR = Path(__file__).resolve().parent
WEB_DIR = ROOT_DIR / "web"

app = FastAPI(title="《23:59》末班七号线 — AI NPC 时间循环推理游戏", version="1.1.0")
scenario = load_scenario()
llm_client = LLMClient()
SESSIONS: dict[str, GameState] = {}


class TurnActionPayload(BaseModel):
    type: str
    target: str | None = None
    text: str = ""
    clue_id: str | None = None


class TurnRequest(BaseModel):
    session_id: str
    move: str | None = None
    action: TurnActionPayload


class PuzzleRequest(BaseModel):
    session_id: str
    slots: dict[str, str | None] = Field(default_factory=dict)


class RestartRequest(BaseModel):
    session_id: str
    skip_to_t2: bool = False


class FinalizeRequest(BaseModel):
    session_id: str


def _get_session(session_id: str) -> GameState:
    state = SESSIONS.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请刷新页面重新开始。")
    return state


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "title": scenario.world["title"],
        "mock_mode": llm_client.is_mock(),
        "model": llm_client.npc_model,
    }


@app.post("/api/session")
async def create_session() -> dict[str, Any]:
    state = create_new_game(scenario)
    state.flags["last_broadcast_turn"] = 1
    SESSIONS[state.session_id] = state
    t1 = scenario.timeline["turns"]["1"]
    intro_events = [
        {
            "kind": "broadcast",
            "actor": None,
            "target": None,
            "zone": None,
            "text": f"{t1['broadcast']}\n{t1['window_event']}",
        }
    ]
    return {
        "session_id": state.session_id,
        "events": intro_events,
        "view": build_view(state, scenario),
        "inspector": build_inspector(state),
    }


@app.post("/api/turn")
async def run_turn(
    req: TurnRequest,
    x_user_token: str | None = Header(default=None, alias="X-User-Token"),
) -> dict[str, Any]:
    state = _get_session(req.session_id)
    try:
        events = await process_turn(
            state,
            req.move,
            req.action.model_dump(),
            scenario,
            llm_client,
            user_token=x_user_token,
        )
    except TurnInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "events": events,
        "view": build_view(state, scenario),
        "inspector": build_inspector(state),
    }


@app.post("/api/puzzle")
async def submit_puzzle(req: PuzzleRequest) -> dict[str, Any]:
    state = _get_session(req.session_id)
    solved, hint = evaluate_puzzle(state, req.slots, scenario)
    return {
        "solved": solved,
        "hint": hint,
        "view": build_view(state, scenario),
    }


@app.post("/api/finalize")
async def finalize_turn8(
    req: FinalizeRequest,
    x_user_token: str | None = Header(default=None, alias="X-User-Token"),
) -> dict[str, Any]:
    state = _get_session(req.session_id)
    events = await finalize_midnight(state, scenario, llm_client, user_token=x_user_token)
    return {
        "events": events,
        "view": build_view(state, scenario),
        "inspector": build_inspector(state),
    }


@app.post("/api/restart")
async def restart_session(req: RestartRequest) -> dict[str, Any]:
    state = _get_session(req.session_id)
    can_skip = state.loop_count > 1 or len(state.endings_seen) > 0
    skip = bool(req.skip_to_t2 and can_skip)
    intro_events = reset_loop(state, scenario, skip_to_t2=skip, increment_loop=True)
    return {
        "events": intro_events,
        "view": build_view(state, scenario),
        "inspector": build_inspector(state),
    }


@app.get("/api/state")
async def get_state(session_id: str = Query(...)) -> dict[str, Any]:
    state = _get_session(session_id)
    return {
        "view": build_view(state, scenario),
        "inspector": build_inspector(state),
    }


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")
