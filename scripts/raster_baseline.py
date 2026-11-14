"""Build step 6: the raster baseline. One vision call per image returns all 12 CubiCasa counts;
the questions are then scored against them. This is the number the propose-and-verify pipeline
must beat, per tier, on accuracy and cost.

    export VERDA_INFERENCE_KEY=...
    uv run python scripts/raster_baseline.py data/preview/junction-dataset-preview/questions.jsonl --split train
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constructor import vlm  # noqa: E402
from constructor.batch import FIELDS, load_questions, tier_of  # noqa: E402
from constructor.extractors import raster  # noqa: E402
from constructor.mapper import map_rules  # noqa: E402
from constructor.scoring import is_correct  # noqa: E402
from constructor.split import split_of  # noqa: E402

# The extractor's prompt, so the baseline and the app measure the same thing.
FIELDS_TO_COUNT, PROMPT, SCHEMA = raster.COUNT_FIELDS, raster.COUNT_PROMPT, raster.COUNT_SCHEMA

# Mapper output -> baseline field.
FIELD_OF = {
    ("count_elements", "window"): "windows", ("count_elements", "door"): "doors",
    ("count_elements", "wc"): "wc_seats", ("count_elements", "sink"): "sinks",
    ("count_elements", "shower_or_bathtub"): "showers_and_bathtubs", ("count_storeys", None): "storeys",
    ("count_rooms", "sauna"): "saunas", ("count_rooms", "kitchen"): "kitchens",
    ("count_rooms", "bedroom"): "bedrooms", ("count_rooms", "bathroom"): "bathrooms",
    ("count_rooms", "wc_room"): "wc_rooms", ("count_rooms", "balcony"): "balconies",
}


def field_of(question: str) -> str | None:
    m = map_rules(question)
    return FIELD_OF.get((m.template, m.params.get("element") or m.params.get("room_type")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", type=Path)
    ap.add_argument("--split", choices=["train", "heldout", "all"], default="train")
    ap.add_argument("--limit", type=int, help="images")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    rows = [r for r in load_questions(args.questions) if r[FIELDS["drawing"]].startswith("data/cubicasa5k/")]
    if args.split != "all":
        rows = [r for r in rows if split_of(r[FIELDS["drawing"]]) == args.split]
    images = sorted({r[FIELDS["drawing"]] for r in rows})[: args.limit]

    def run(path: str):
        try:
            return path, vlm.chat([vlm.image_part(args.questions.parent / path), {"type": "text", "text": PROMPT}], schema=SCHEMA, max_tokens=300)
        except Exception as e:  # one bad image must not stop the run
            return path, e

    with ThreadPoolExecutor(args.workers) as pool:
        replies = dict(pool.map(run, images))

    errors = {p: r for p, r in replies.items() if isinstance(r, Exception)}
    ok = {p: r for p, r in replies.items() if not isinstance(r, Exception)}
    n, correct = Counter(), Counter()
    diffs: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        path = r[FIELDS["drawing"]]
        if path not in ok:
            continue
        field = field_of(r[FIELDS["question"]])
        pred = ok[path].json().get(field) if field else None
        for key in ("all", tier_of(path), f"field:{field}"):
            n[key] += 1
            correct[key] += is_correct(pred, r[FIELDS["answer"]], "count")
        if pred is not None:
            diffs[field][pred - r[FIELDS["answer"]]] += 1

    tokens_in = sum(r.prompt_tokens for r in ok.values())
    tokens_out = sum(r.completion_tokens for r in ok.values())
    fresh = [r for r in ok.values() if not r.cached]
    print(f"images {len(ok)} ok, {len(errors)} failed; calls this run {len(fresh)}, "
          f"mean latency {sum(r.seconds for r in fresh) / max(len(fresh), 1):.1f}s")
    print(f"tokens per image: {tokens_in / max(len(ok), 1):.0f} in, {tokens_out / max(len(ok), 1):.0f} out; "
          f"cost per image ${sum(r.cost_usd for r in ok.values()) / max(len(ok), 1):.5f} (at VLM_PRICE_*)")
    for key in sorted(n, key=lambda k: (k.startswith("field:"), -n[k])):
        d = dict(diffs[key[6:]].most_common(4)) if key.startswith("field:") else ""
        print(f"{key:<40} {n[key]:>5} {correct[key] / n[key]:>7.1%}  {d}")
    for p, e in list(errors.items())[:5]:
        print("error:", p, type(e).__name__, e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
