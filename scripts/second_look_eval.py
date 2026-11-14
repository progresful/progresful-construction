"""Does a second look (plan shown with found doors/windows boxed, asked for missed ones) improve
door and window counts? Train split only.

    uv run python scripts/second_look_eval.py data/preview/junction-dataset-preview/questions.jsonl
"""

from __future__ import annotations

import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constructor.batch import FIELDS, load_questions  # noqa: E402
from constructor.extractors import raster  # noqa: E402
from constructor.ingest import load_cached  # noqa: E402
from constructor.mapper import map_rules  # noqa: E402
from constructor.split import split_of  # noqa: E402


def main() -> int:
    questions = Path(sys.argv[1])
    split = sys.argv[2] if len(sys.argv) > 2 else "train"
    gold: dict[str, dict[str, int]] = {}
    for r in load_questions(questions):
        p = r[FIELDS["drawing"]]
        if not p.startswith("data/cubicasa5k/") or split_of(p) != split:
            continue
        m = map_rules(r[FIELDS["question"]])
        if m.template == "count_elements" and m.params.get("element") in ("door", "window") and len(m.params) == 1:
            gold.setdefault(p, {})[m.params["element"]] = r[FIELDS["answer"]]

    def run(p: str):
        d = load_cached(questions.parent / p)
        if d is None:
            return None
        image = Path(d.plan_image or d.drawing)
        boxes = [(e.type, e.bbox) for e in d.elements if e.type in ("door", "window") and e.bbox]
        extra, _ = raster.second_look(image, boxes)
        return p, Counter(k for k, _ in boxes), Counter(k for k, _ in extra)

    with ThreadPoolExecutor(8) as pool:
        results = [r for r in pool.map(run, sorted(gold)) if r]
    for kind in ("door", "window"):
        n = before = after = under = over = soft = 0
        for p, base, extra in results:
            if kind not in gold[p]:
                continue
            g = gold[p][kind]
            n += 1
            before += base[kind] == g
            after += base[kind] + extra[kind] == g
            soft += base[kind] + round(raster.SECOND_LOOK_CONF * extra[kind] + 1e-9) == g
            under += base[kind] + extra[kind] < g
            over += base[kind] + extra[kind] > g
        print(f"{kind:<7} n={n:>3}  first look {before / n:6.1%}  with second look {after / n:6.1%}  (after: {under} under, {over} over)  as uncertain marks {soft / n:6.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
