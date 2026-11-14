"""Nemotron 3.5 Super VL client (OpenAI-compatible vLLM endpoint on DataCrunch/Verda).

The key comes from VERDA_INFERENCE_KEY only. Responses are cached on disk by request hash,
so reruns of the same prompt on the same image cost nothing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BASE_URL = os.environ.get("VERDA_BASE_URL", "https://containers.datacrunch.io/nemotron-3-5-super-vl-b300/v1")
MODEL = "nemotron-3.5-super-vl"
CACHE = Path("cache/vlm")

# List price per million tokens, for the cost report. The endpoint is a dedicated container
# billed per hour, so per-token price is an assumption to set once known (SPEC.md, Cost).
PRICE_IN = float(os.environ.get("VLM_PRICE_IN_PER_M", "0"))
PRICE_OUT = float(os.environ.get("VLM_PRICE_OUT_PER_M", "0"))


@dataclass
class Reply:
    content: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    cached: bool

    @property
    def cost_usd(self) -> float:
        return (self.prompt_tokens * PRICE_IN + self.completion_tokens * PRICE_OUT) / 1e6

    def json(self):
        return json.loads(self.content)


def image_part(path: Path) -> dict:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


# Set after a call fails outright: later calls in this process answer from cache only, so a dead
# endpoint costs one timeout instead of one per drawing.
_down = False


def chat(content: list[dict] | str, schema: dict | None = None, max_tokens: int = 1024, retries: int = 2,
         timeout: float = 120) -> Reply:
    key = os.environ.get("VERDA_INFERENCE_KEY")
    if not key:
        raise RuntimeError("VERDA_INFERENCE_KEY is not set")
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": 0,
        # Counting needs no hidden reasoning; it would spend the token budget before answering.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if schema is not None:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}}

    raw = json.dumps(body, sort_keys=True).encode()
    cache_file = CACHE / f"{hashlib.sha256(raw).hexdigest()[:24]}.json"
    if cache_file.exists():
        c = json.loads(cache_file.read_text())
        return Reply(c["content"], c["prompt_tokens"], c["completion_tokens"], 0.0, True)
    global _down
    if _down:
        raise ConnectionError("Nemotron endpoint unreachable earlier in this run")

    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions", data=raw,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(retries):
        try:
            start = time.time()
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.load(r)
            break
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries - 1:
                _down = True
                raise
            time.sleep(2 ** attempt)
    usage = resp.get("usage") or {}
    reply = Reply(
        content=resp["choices"][0]["message"]["content"] or "",
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        seconds=time.time() - start,
        cached=False,
    )
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"content": reply.content, "prompt_tokens": reply.prompt_tokens,
                                      "completion_tokens": reply.completion_tokens}))
    return reply
