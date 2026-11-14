"""Scoring, per the dataset README: counts exact; areas, lengths and volumes within 2%;
text answers free-form (scored here by normalised match, which undercounts; review by hand).

The gold unit decides how to score. Predicted values in another unit are converted.
"""

from __future__ import annotations

import re

REL_TOLERANCE = 0.02

# Factor to convert from the key unit into SI (m, m2, m3).
TO_SI = {"m": 1.0, "ft": 0.3048, "m2": 1.0, "ft2": 0.09290304, "m3": 1.0, "ft3": 0.028316846592}


def _number(x) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(x))
    return float(m.group().replace(",", ".")) if m else None


def _normalise(s) -> str:
    return re.sub(r"[^\w]+", " ", str(s).casefold()).strip()


def convert(value: float, from_unit: str | None, to_unit: str | None) -> float:
    if from_unit == to_unit or from_unit not in TO_SI or to_unit not in TO_SI:
        return value
    return value * TO_SI[from_unit] / TO_SI[to_unit]


def is_correct(predicted, gold, gold_unit: str | None, predicted_unit: str | None = None) -> bool:
    if predicted is None:
        return False
    if gold_unit == "count":
        p, g = _number(predicted), _number(gold)
        return p is not None and g is not None and p == g
    if gold_unit in TO_SI:
        p, g = _number(predicted), _number(gold)
        if p is None or g is None:
            return False
        p = convert(p, predicted_unit or gold_unit, gold_unit)
        return abs(p - g) <= REL_TOLERANCE * abs(g)
    return _normalise(predicted) == _normalise(gold)
