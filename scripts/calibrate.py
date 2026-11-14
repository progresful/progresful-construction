"""Calibrate raster count ranges on train: per type and per counting route (marks or whole image), the 10th and 90th percentile of
(gold - mark count). Writes constructor/calibration.json and reports how often the resulting
range contains the true count, on train and held-out.

    uv run python scripts/calibrate.py data/preview/junction-dataset-preview/questions.jsonl
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constructor import templates  # noqa: E402
from constructor.answer import answer  # noqa: E402
from constructor.batch import FIELDS, load_questions  # noqa: E402
from constructor.ingest import load_cached  # noqa: E402
from constructor.split import split_of  # noqa: E402

LOW, HIGH = 0.10, 0.90


def quantile(values: list[int], q: float) -> int:
    v = sorted(values)
    return v[min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))]


def rows(questions: Path, split: str):
    for r in load_questions(questions):
        p = r[FIELDS["drawing"]]
        if not p.startswith("data/cubicasa5k/") or split_of(p) != split:
            continue
        d = load_cached(questions.parent / p)
        if d is None:
            continue
        a = answer(d, r[FIELDS["question"]])
        if a.value is None or a.unit != "count":
            continue
        what = a.params.get("element") or a.params.get("room_type") or ("storey" if a.template == "count_storeys" else None)
        if a.evidence_ids and what:  # counted from marks
            yield what, a, r[FIELDS["answer"]]
        elif what in templates.COUNT_KEYS:  # whole-image count
            yield f"whole:{templates.COUNT_KEYS[what]}", a, r[FIELDS["answer"]]


def main() -> int:
    questions = Path(sys.argv[1])
    templates.CALIBRATION_FILE.unlink(missing_ok=True)
    templates.calibration.cache_clear()
    errors: dict[str, list[int]] = defaultdict(list)
    for what, a, gold in rows(questions, "train"):
        errors[what].append(gold - a.value)
        # Misses grow with the count: a studio's one window is not off by 7 like a house's twelve.
        errors[f"{what}@{templates.size_bucket(a.value)}"].append(gold - a.value)
    bands = {w: {"lo": quantile(e, LOW), "hi": quantile(e, HIGH), "n": len(e)} for w, e in errors.items()
             if "@" not in w or len(e) >= templates.MIN_BUCKET}
    templates.CALIBRATION_FILE.write_text(json.dumps(bands, indent=2, sort_keys=True))
    templates.calibration.cache_clear()
    print("bands (gold - count):", {w: (b["lo"], b["hi"]) for w, b in sorted(bands.items()) if not w.startswith("whole:")})
    for split in ("train", "heldout"):
        inside, total, exact = defaultdict(int), defaultdict(int), defaultdict(int)
        for what, a, gold in rows(questions, split):
            total[what] += 1
            exact[what] += a.value == gold
            lo, hi = a.range or (a.value, a.value)  # no range: the value is the whole claim
            inside[what] += lo <= gold <= hi
        print(f"{split}: value right / range contains the truth")
        for w in sorted(total):
            print(f"  {w:<28} n={total[w]:>4}  {exact[w] / total[w]:6.1%}  {inside[w] / total[w]:6.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
