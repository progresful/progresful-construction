"""Marks versus whole-image counts, per CubiCasa type, on a split (train for tuning).
A room type should move into raster.ROOM_MARKED_TYPES only if its marks win here.

    uv run python scripts/raster_marks_eval.py data/preview/junction-dataset-preview/questions.jsonl --limit 60
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constructor.batch import FIELDS, load_questions, tier_of  # noqa: E402
from constructor.extractors import raster  # noqa: E402
from constructor.mapper import map_rules  # noqa: E402
from constructor.split import split_of  # noqa: E402
from constructor.templates import COUNT_KEYS  # noqa: E402


def marks_count(d, what: str) -> int:
    if what in ("window", "door"):
        return sum(1 for e in d.elements if e.type == what)
    return sum(1 for e in d.elements if e.type == "room" and e.room_type == what)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", type=Path)
    ap.add_argument("--split", default="train")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    gold: dict[str, dict[str, int]] = defaultdict(dict)
    for r in load_questions(args.questions):
        p = r[FIELDS["drawing"]]
        if not p.startswith("data/cubicasa5k/") or split_of(p) != args.split:
            continue
        m = map_rules(r[FIELDS["question"]])
        what = m.params.get("element") or m.params.get("room_type")
        if what in ("window", "door") or (m.template == "count_rooms" and what in COUNT_KEYS):
            gold[p][what] = r[FIELDS["answer"]]
    ordered = sorted(gold)
    images = ordered[:: max(1, len(ordered) // args.limit)][: args.limit]

    def run(p):
        try:
            return p, raster.extract(args.questions.parent / p)
        except Exception as e:
            return p, e

    with ThreadPoolExecutor(args.workers) as pool:
        results = dict(pool.map(run, images))

    n, win_marks, win_base = Counter(), Counter(), Counter()
    diffs: dict[str, Counter] = defaultdict(Counter)
    for p, d in results.items():
        if isinstance(d, Exception):
            print("error", p, type(d).__name__, d)
            continue
        for what, g in gold[p].items():
            mk, base = marks_count(d, what), (d.counts or {}).get(COUNT_KEYS[what])
            for key in (what, f"{what}:{tier_of(p)}"):
                n[key] += 1
                win_marks[key] += mk == g
                win_base[key] += base == g
            diffs[what][mk - g] += 1
    print(f"images {sum(not isinstance(d, Exception) for d in results.values())}")
    for key in sorted(n, key=lambda k: (":" in k, k)):
        flag = "  <- marks win" if ":" not in key and win_marks[key] > win_base[key] else ""
        print(f"{key:<48} n={n[key]:>3}  marks {win_marks[key] / n[key]:6.1%}  whole-image {win_base[key] / n[key]:6.1%}{flag}")
    for what, c in diffs.items():
        print(f"  {what:<10} marks - gold: {sorted(c.items())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
