from __future__ import annotations

import json
import re
from typing import Any

from .llm import LLMClient
from .scenario import ScenarioData


def keyword_tag(text: str, scenario: ScenarioData) -> list[str]:
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return []
    hits: list[str] = []
    for tag_id, cfg in scenario.tags.items():
        for kw in cfg.get("keywords", []):
            if kw.lower() in cleaned:
                hits.append(tag_id)
                break
    return hits


def _extract_json_obj(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first == -1 or last == -1 or last < first:
        return None
    try:
        obj = json.loads(cleaned[first : last + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


async def extract_tags(
    text: str,
    scenario: ScenarioData,
    llm: LLMClient,
    user_token: str | None = None,
) -> list[str]:
    """Two-tier tagger: fast deterministic keywords first; LLM fallback only if no hit and len >= 6."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    hits = keyword_tag(cleaned, scenario)
    if hits:
        return hits

    if len(cleaned) < 6 or llm.is_mock(user_token):
        return []

    defs = "\n".join(f"- {tid}: {cfg['desc']}" for tid, cfg in scenario.tags.items())
    system_prompt = scenario.tagger_prompt_template.format(tag_definitions=defs)
    try:
        raw, _ = await llm.complete(
            system_prompt,
            f"玩家说的话：{cleaned}",
            role_kind="tagger",
            user_token=user_token,
            temperature=0.0,
            max_tokens=120,
        )
        obj = _extract_json_obj(raw)
        if not obj or not isinstance(obj.get("tags"), list):
            return []
        valid = set(scenario.tags.keys())
        return [t for t in obj["tags"] if isinstance(t, str) and t in valid]
    except Exception:
        return []
