"""The one answer function. The app and the batch runner both call answer(); nothing else answers."""

from __future__ import annotations

from typing import Callable

from .mapper import LLMMapper, map_question
from .schema import Answer, Drawing
from .templates import TEMPLATES

# Batch-only: answers an unmapped question from the whole image. Never used by the app.
Fallback = Callable[[Drawing, str], Answer]


def answer(
    drawing: Drawing,
    question: str,
    llm: LLMMapper | None = None,
    fallback: Fallback | None = None,
    verify=None,
) -> Answer:
    mapping = map_question(question, llm, verify)
    result = TEMPLATES[mapping.template](drawing, mapping.params) if mapping.template else None

    if result is None and fallback is not None:
        result = fallback(drawing, question)
        result.fallback = True
        result.exact = False
    if result is None:
        return Answer.cannot_answer(cost_usd=mapping.cost_usd)

    result.cost_usd += mapping.cost_usd
    return result
