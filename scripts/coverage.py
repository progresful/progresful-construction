"""Template coverage on a split: how many questions map, and whether the template's unit
matches the gold unit. Needs no extractors.

    uv run python scripts/coverage.py data/preview/junction-dataset-preview/questions.jsonl --split train
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constructor.batch import FIELDS, load_questions, tier_of  # noqa: E402
from constructor.mapper import map_rules  # noqa: E402
from constructor.split import split_of  # noqa: E402

TEMPLATE_UNIT = {
    "count_elements": "count", "count_rooms": "count", "count_storeys": "count",
    "room_area": "m2", "total_area": "m2", "apartment_area": "m2", "wall_side_area": "m2",
    "wall_length": "m", "element_volume": "m3",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", type=Path)
    ap.add_argument("--split", choices=["train", "heldout", "all"], default="train")
    ap.add_argument("--show", type=int, default=15, help="unmapped / mismatched examples to print")
    args = ap.parse_args()

    rows = load_questions(args.questions)
    if args.split != "all":
        rows = [r for r in rows if split_of(r[FIELDS["drawing"]]) == args.split]

    by_tier: dict[str, Counter] = defaultdict(Counter)
    templates: Counter = Counter()
    unmapped: Counter = Counter()
    mismatched: list[str] = []
    for r in rows:
        q, tier, gold_unit = r[FIELDS["question"]], tier_of(r[FIELDS["drawing"]]), r.get(FIELDS["unit"])
        m = map_rules(q)
        by_tier[tier]["n"] += 1
        if m.template is None:
            unmapped[(tier, re.sub(r"\d+", "N", q)[:140])] += 1
            continue
        templates[(m.template, m.params.get("element") or m.params.get("room_type") or "")] += 1
        if TEMPLATE_UNIT[m.template] != gold_unit:
            # ft2 gold answers are converted at scoring time, so they are not a mismatch.
            if not (TEMPLATE_UNIT[m.template] == "m2" and gold_unit == "ft2"):
                by_tier[tier]["mismatch"] += 1
                mismatched.append(f"{gold_unit} vs {m.template}{m.params}: {q[:120]}")
                continue
        by_tier[tier]["ok"] += 1

    total = Counter()
    print(f"{'tier':<40} {'n':>6} {'mapped':>8} {'unit ok':>8}")
    for tier, c in sorted(by_tier.items(), key=lambda kv: -kv[1]["n"]):
        total.update(c)
        print(f"{tier:<40} {c['n']:>6} {(c['ok'] + c['mismatch']) / c['n']:>8.1%} {c['ok'] / c['n']:>8.1%}")
    print(f"{'ALL':<40} {total['n']:>6} {(total['ok'] + total['mismatch']) / total['n']:>8.1%} {total['ok'] / total['n']:>8.1%}")

    print("\ntemplates:")
    for (t, sub), n in templates.most_common():
        print(f"  {n:>5} {t} {sub}")
    print(f"\nunit mismatches ({len(mismatched)}):")
    for line in mismatched[: args.show]:
        print("  " + line)
    print(f"\nunmapped ({sum(unmapped.values())}):")
    for (tier, q), n in unmapped.most_common(args.show):
        print(f"  {n:>4} {tier:<16} {q}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
