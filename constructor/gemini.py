"""Gemini client (Google Generative Language API, REST). Key from GEMINI_API_KEY only.
Responses are cached on disk by request hash, so reruns cost nothing.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API = "https://generativelanguage.googleapis.com/v1beta/models"
CACHE = Path("cache/gemini")
# 3.8 flash beat 3.5 flash on window/door/fixture detection (scripts/gemini_detect_eval.py, train).
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

THINKING_HEADROOM = 4096

# List price per million tokens, for the cost report; set for the model in use.
PRICE_IN = float(os.environ.get("GEMINI_PRICE_IN_PER_M", "0"))
PRICE_OUT = float(os.environ.get("GEMINI_PRICE_OUT_PER_M", "0"))


@dataclass
class Reply:
    text: str
    prompt_tokens: int
    completion_tokens: int
    seconds: float
    cached: bool

    @property
    def cost_usd(self) -> float:
        return (self.prompt_tokens * PRICE_IN + self.completion_tokens * PRICE_OUT) / 1e6

    def json(self):
        t = self.text.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(t)


def image(path: Path) -> dict:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return {"inline_data": {"mime_type": mime, "data": base64.b64encode(path.read_bytes()).decode()}}


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def generate(parts: list[dict | str], model: str = DEFAULT_MODEL, schema: dict | None = None,
             max_tokens: int = 4096, thinking_budget: int | None = 0, retries: int = 3) -> Reply:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    # Gemini 3.x models think even with a zero budget, and thoughts count against the output limit:
    # without headroom a short answer is cut off before it starts.
    config: dict = {"temperature": 0, "maxOutputTokens": max_tokens + THINKING_HEADROOM}
    if thinking_budget is not None:
        config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
    if schema is not None:
        config["responseMimeType"] = "application/json"
        config["responseSchema"] = schema
    body = {
        "contents": [{"role": "user", "parts": [p if isinstance(p, dict) else {"text": p} for p in parts]}],
        "generationConfig": config,
    }
    raw = json.dumps(body, sort_keys=True).encode()
    cache_file = CACHE / f"{model}-{hashlib.sha256(raw).hexdigest()[:24]}.json"
    if cache_file.exists():
        c = json.loads(cache_file.read_text())
        return Reply(c["text"], c["prompt_tokens"], c["completion_tokens"], 0.0, True)

    req = urllib.request.Request(f"{API}/{model}:generateContent", data=raw,
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            start = time.time()
            with urllib.request.urlopen(req, timeout=300) as r:
                resp = json.load(r)
            break
        except urllib.error.HTTPError as e:
            # 429 / 5xx are worth a retry; anything else is a request bug.
            if e.code not in (429, 500, 502, 503, 504) or attempt == retries - 1:
                raise RuntimeError(f"Gemini {e.code}: {e.read()[:300]!r}") from None
            time.sleep(2 ** (attempt + 1))
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as e:
            # Dropped connections ("Remote end closed connection") happen under load: retry them too.
            if attempt == retries - 1:
                raise RuntimeError(f"Gemini unreachable: {type(e).__name__}: {e}") from None
            time.sleep(2 ** (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    cand = (resp.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []) if not p.get("thought"))
    if cand.get("finishReason") not in (None, "STOP") or not text.strip():
        # A cut-off or empty reply is an error, never cached: a cached one would be served forever.
        raise RuntimeError(f"Gemini reply unusable: finishReason={cand.get('finishReason')}, {len(text)} chars")
    usage = resp.get("usageMetadata", {})
    reply = Reply(text, usage.get("promptTokenCount", 0),
                  usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
                  time.time() - start, False)
    CACHE.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"text": reply.text, "prompt_tokens": reply.prompt_tokens,
                                      "completion_tokens": reply.completion_tokens}))
    return reply
