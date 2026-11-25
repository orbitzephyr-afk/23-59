from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Awaitable, Callable

from openai import AsyncOpenAI


class LLMClient:
    """OpenAI-compatible async client targeting ModelScope API-Inference, local vLLM/SGLang, or mock mode."""

    def __init__(self) -> None:
        self.mock_override: Callable[[str, str, str], Awaitable[str] | str] | None = None

    @property
    def base_url(self) -> str:
        return os.getenv("LLM_BASE_URL", "https://api-inference.modelscope.cn/v1/").strip()

    @property
    def api_key(self) -> str:
        return os.getenv("LLM_API_KEY", "").strip()

    @property
    def npc_model(self) -> str:
        return os.getenv("NPC_MODEL", "Qwen/Qwen2.5-7B-Instruct").strip()

    @property
    def tagger_model(self) -> str:
        return os.getenv("TAGGER_MODEL", self.npc_model).strip()

    @property
    def timeout(self) -> float:
        try:
            return float(os.getenv("LLM_TIMEOUT", "20"))
        except ValueError:
            return 20.0

    def is_mock(self, user_token: str | None = None) -> bool:
        if self.mock_override is not None:
            return True
        flag = os.getenv("LLM_MOCK", "").strip()
        if flag == "1":
            return True
        if flag == "0":
            return False
        # Default to mock when neither server key nor user token is provided,
        # so local startup and Spaces previews work immediately without crashing.
        return not bool((user_token or "").strip() or self.api_key)

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        role_kind: str = "npc",
        npc_id: str = "",
        user_token: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 300,
    ) -> tuple[str, int]:
        start = time.perf_counter()

        if self.mock_override is not None:
            res = self.mock_override(role_kind, npc_id, user_prompt)
            if asyncio.iscoroutine(res):
                res = await res
            ms = int((time.perf_counter() - start) * 1000)
            return str(res), ms

        if self.is_mock(user_token):
            await asyncio.sleep(0.02)
            ms = int((time.perf_counter() - start) * 1000)
            if role_kind == "tagger":
                return json.dumps({"tags": []}, ensure_ascii=False), ms
            return "", ms

        token = (user_token or "").strip() or self.api_key
        if not token:
            raise RuntimeError("Missing ModelScope API token (LLM_API_KEY or X-User-Token)")

        model = self.tagger_model if role_kind == "tagger" else self.npc_model
        client = AsyncOpenAI(
            api_key=token,
            base_url=self.base_url,
            timeout=self.timeout,
        )
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            timeout=self.timeout,
        )
        content = (resp.choices[0].message.content or "").strip()
        ms = int((time.perf_counter() - start) * 1000)
        return content, ms
