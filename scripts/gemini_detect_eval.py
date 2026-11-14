"""Gemini element detection (boxes) versus whole-image counts, per CubiCasa type, on a split.

    uv run python scripts/gemini_detect_eval.py data/preview/junction-dataset-preview/questions.jsonl --limit 60
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
from constructor.ingest import load_cached  # noqa: E402
from constructor.mapper import map_rules  # noqa: E402
from constructor.split import split_of  # noqa: E402
from constructor.templates import COUNT_KEYS, ELEMENT_TYPES  # noqa: E402

TYPES = ["window", "door", "wc", "sink", "shower_or_bathtub"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", type=Path)
    ap.add_argument("--split", default="train")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    gold: dict[str, dict[str, int]] = defaultdict(dict)
    for r in load_questions(args.questions):
        p = r[FIELDS["drawing"]]
        if p.startswith("data/cubicasa5k/") and split_of(p) == args.split:
            m = map_rules(r[FIELDS["question"]])
            if m.template == "count_elements" and m.params.get("element") in TYPES:
                gold[p][m.params["element"]] = r[FIELDS["answer"]]
    ordered = sorted(gold)
    images = ordered[:: max(1, len(ordered) // args.limit)][: args.limit]

    def run(p):
        kw = {"model": args.model} if args.model else {}
        try:
            return p, raster.detect_elements(args.questions.parent / p, **kw)
        except Exception as e:
            return p, e

    with ThreadPoolExecutor(8) as pool:
        results = dict(pool.map(run, images))
    n, win, base = Counter(), Counter(), Counter()
    diffs: dict[str, Counter] = defaultdict(Counter)
    secs = []
    for p, res in results.items():
        if isinstance(res, Exception):
            print("error", p, res)
            continue
        boxes, reply = res
        secs.append(reply.seconds)
        cached = load_cached(args.questions.parent / p)
        for what, g in gold[p].items():
            got = sum(1 for kind, _ in boxes if kind in ELEMENT_TYPES.get(what, {what}))
            b = (cached.counts or {}).get(COUNT_KEYS[what]) if cached else None
            for key in (what, f"{what}:{tier_of(p)}"):
                n[key] += 1
                win[key] += got == g
                base[key] += b == g
            diffs[what][got - g] += 1
    print(f"images {len(secs)}, mean latency {sum(secs) / max(len(secs), 1):.1f}s (0 = cached)")
    for key in sorted(n, key=lambda k: (":" in k, k)):
        flag = "  <- boxes win" if ":" not in key and win[key] > base[key] else ""
        print(f"{key:<48} n={n[key]:>3}  boxes {win[key] / n[key]:6.1%}  whole-image {base[key] / n[key]:6.1%}{flag}")
    for what, c in diffs.items():
        print(f"  {what:<18} boxes - gold: {sorted(c.items())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
