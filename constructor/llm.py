"""Text-side Gemini use: map unrecognised questions to a template, and phrase answers in the
asker's language. Both are optional: without GEMINI_API_KEY the rule-based mapper and English
answers are used. Neither ever produces a value; values come only from templates.
"""

from __future__ import annotations

import os
import re

from . import gemini
from .mapper import Mapping
from .templates import TEMPLATES

# Flash, not flash-lite: lite confused counts with areas and storeys with room labels.
TEXT_MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-3.8-flash")

CATALOGUE = """Templates and their params:
- count_elements: {"element": one of window, door, wc, sink, shower, bathtub, shower_or_bathtub, wall, column, beam, stair, slab, apartment, space; optional "storey" or "model" (names exactly as quoted in the question)}
- count_rooms: {"room_type": one of bedroom, bathroom, kitchen, sauna, wc_room, balcony, living_room, hall, closet, storage} or {"label": room name exactly as quoted}
- count_storeys: {}
- room_area: {"name": room name as quoted, optional "storey"} or {"number": room number, optional "label"}
- total_area: {} or {"storey": name} or {"label": room name as quoted} or {"scope": "numbered_indoor"}
- apartment_area: {"apartment": letter}
- wall_length: {optional "storey"}
- wall_side_area: {optional "storey"}
- element_volume: {"element": wall or slab, optional "storey"}"""

MAP_PROMPT = """You map questions about a construction drawing to one answer template. The question may be in any language.
{catalogue}

Rules:
- Pick a template only if it answers the question exactly as asked.
- count_* templates answer "how many" questions only. Questions about size, area or "how big" use room_area or total_area; length, volume and side area have their own templates.
- A name given after floor, storey, level or plan (in any language) is a "storey", not a room "label".
- If the question adds a condition no template can express (for example "interior doors", "on the north facade", "with access to outdoor space", "fire rating"), or asks for something else entirely, return template "none".
- Never invent params; copy names as they appear in the question.

Question: {question}"""

MAP_SCHEMA = {
    "type": "object",
    "properties": {
        "template": {"type": "string"},
        "params": {
            "type": "object",
            "properties": {k: {"type": "string"} for k in ("element", "room_type", "label", "name", "number", "storey", "model", "apartment", "scope")},
        },
    },
    "required": ["template", "params"],
}

ALLOWED_PARAMS = {"element", "room_type", "label", "name", "number", "storey", "model", "apartment", "scope"}


def gemini_mapper(question: str) -> Mapping:
    reply = gemini.generate([MAP_PROMPT.format(catalogue=CATALOGUE, question=question)], model=TEXT_MODEL,
                            schema=MAP_SCHEMA, max_tokens=300)
    try:
        out = reply.json()
    except ValueError:
        return Mapping(None, cost_usd=reply.cost_usd)
    template = out.get("template")
    if template not in TEMPLATES:
        return Mapping(None, cost_usd=reply.cost_usd)
    params = {k: v for k, v in (out.get("params") or {}).items() if k in ALLOWED_PARAMS and v not in (None, "")}
    if params.get("apartment"):
        params["apartment"] = params["apartment"].strip().upper()[:1]
    return Mapping(template, params, cost_usd=reply.cost_usd)


PHRASE_PROMPT = """Rewrite this answer in the language of the question. Keep every number, unit and count exactly as given, add nothing, and keep it to one or two short sentences. If the question is in English, return the answer unchanged.

Question: {question}
Answer: {answer}"""


ENGLISH = re.compile(r"\b(how|what|which|is|are|the|many|much|area|there)\b", re.I)


def looks_english(question: str) -> bool:
    return question.isascii() and len(ENGLISH.findall(question)) >= 2


def phrase(question: str, english: str) -> tuple[str, float]:
    """The answer sentence in the question's language, and the call's cost. English questions
    skip the call (it would only add latency)."""
    if looks_english(question):
        return english, 0.0
    reply = gemini.generate([PHRASE_PROMPT.format(question=question, answer=english)], model=TEXT_MODEL, max_tokens=200)
    text = reply.text.strip()
    return (text or english), reply.cost_usd


KEY_PARAMS = ("element", "room_type", "label", "apartment", "scope")


def verify(question: str, mapping: Mapping) -> Mapping:
    """Overrule a rule match on a non-English question when Gemini reads it differently. The rules'
    condition check only knows English ("ovea avautuu kylpyhuoneeseen" matched plain "doors")."""
    if looks_english(question):
        return mapping
    g = gemini_mapper(question)
    if g.template is None:
        return Mapping(None, cost_usd=g.cost_usd)  # a condition no template expresses
    same = g.template == mapping.template and all(g.params.get(k) == mapping.params.get(k) for k in KEY_PARAMS)
    return Mapping(mapping.template, mapping.params, cost_usd=g.cost_usd) if same else g


def verifier():
    """The rule-match check when a Gemini key is set, else None."""
    return verify if gemini.available() else None


def mapper():
    """The Gemini fallback mapper when a key is set, else None."""
    return gemini_mapper if gemini.available() else None
