"""Batch runner: questions.jsonl through answer(), then accuracy and cost per source, tier and template.

    uv run constructor-batch data/preview/questions.jsonl --split train
    uv run constructor-batch data/preview/questions.jsonl --split heldout   # deck numbers only
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .answer import answer
from .ingest import ensure_extracted
from .scoring import is_correct
from .split import split_of

# questions.jsonl field names, from the dataset README: {"path", "question", "answer", "unit", "type"}.
FIELDS = {"drawing": "path", "question": "question", "answer": "answer", "unit": "unit", "type": "type"}


def tier_of(path: str) -> str:
    # CubiCasa tier is the file-name prefix (colorful-11397.png); other sources are their own tier.
    parts = Path(path).parts
    source = parts[1] if len(parts) > 2 and parts[0] == "data" else "-"
    if source == "cubicasa5k":
        return "cubicasa/" + Path(path).name.rsplit("-", 1)[0]
    return source


@dataclass
class Bucket:
    questions: int = 0
    correct: int = 0
    answered: int = 0
    exact: int = 0
    fallback: int = 0
    not_extracted: int = 0
    question_cost: float = 0.0
    drawings: dict[str, float] = field(default_factory=dict)  # drawing -> extraction cost

    def add(self, ok: bool, ans, drawing: str, extraction_cost: float) -> None:
        self.questions += 1
        self.correct += ok
        self.answered += ans.answered
        self.exact += ans.exact
        self.fallback += ans.fallback
        self.question_cost += ans.cost_usd
        self.drawings[drawing] = extraction_cost

    def row(self, name: str) -> str:
        n = max(self.questions, 1)
        extraction = sum(self.drawings.values())
        per_drawing = extraction / max(len(self.drawings), 1)
        per_question = self.question_cost / n
        amortised = (self.question_cost + extraction) / n
        return (
            f"{name:<28} {self.questions:>6} {self.correct / n:>7.1%} {self.answered / n:>8.1%} "
            f"{self.exact / n:>6.1%} {self.fallback:>5} {self.not_extracted:>6} "
            f"${per_drawing:>9.5f} ${per_question:>9.6f} ${amortised:>9.6f}"
        )


HEADER = (
    f"{'':<28} {'n':>6} {'acc':>7} {'answered':>8} {'exact':>6} {'fallb':>5} {'noext':>6} "
    f"{'extr/drw':>10} {'cost/q':>10} {'amort/q':>10}"
)


def load_questions(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def resolve(drawing: str, questions_file: Path) -> Path:
    p = Path(drawing)
    return p if p.is_absolute() or p.exists() else questions_file.parent / p


def run(questions_file: Path, split: str, limit: int | None, details: Path | None, allow_paid: bool = False,
        use_llm: bool = False) -> dict[str, dict[str, Bucket]]:
    rows = load_questions(questions_file)
    if split != "all":
        rows = [r for r in rows if split_of(r[FIELDS["drawing"]]) == split]
    if limit:
        rows = rows[:limit]

    groups: dict[str, dict[str, Bucket]] = {
        g: defaultdict(Bucket) for g in ("total", "kind", "tier", "type", "template")
    }
    out = details.open("w") if details else None
    failed: set[str] = set()
    mapper = None
    if use_llm:
        from .llm import mapper as llm_mapper

        mapper = llm_mapper()

    for r in rows:
        drawing_name = r[FIELDS["drawing"]]
        tier = tier_of(drawing_name)
        qtype = str(r.get(FIELDS["type"]) or "-")
        try:
            drawing = ensure_extracted(resolve(drawing_name, questions_file), allow_raster=allow_paid)
        except Exception as e:
            # Extractors not built yet and raster without permission are expected; anything else is a bug to see.
            if not isinstance(e, (NotImplementedError, RuntimeError)) and drawing_name not in failed:
                failed.add(drawing_name)
                print(f"extraction failed: {drawing_name}: {type(e).__name__}: {e}", file=sys.stderr)
            for g, key in (("total", "all"), ("tier", tier), ("type", qtype)):
                groups[g][key].questions += 1
                groups[g][key].not_extracted += 1
            continue

        ans = answer(drawing, r[FIELDS["question"]], llm=mapper)
        ok = is_correct(ans.value, r[FIELDS["answer"]], r.get(FIELDS["unit"]), ans.unit)
        for g, key in (
            ("total", "all"),
            ("kind", drawing.kind),
            ("tier", tier),
            ("type", qtype),
            ("template", ans.template or "(unmapped)"),
        ):
            groups[g][key].add(ok, ans, drawing_name, drawing.extraction_cost_usd)
        if out:
            out.write(json.dumps({**r, "predicted": ans.to_dict(), "correct": ok}, ensure_ascii=False) + "\n")

    if out:
        out.close()
    return groups


def report(groups: dict[str, dict[str, Bucket]]) -> str:
    lines = []
    for g, buckets in groups.items():
        lines.append(f"\n== by {g} ==")
        lines.append(HEADER)
        for name, b in sorted(buckets.items(), key=lambda kv: -kv[1].questions):
            lines.append(b.row(name))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("questions", type=Path)
    ap.add_argument("--split", choices=["train", "heldout", "all"], default="train")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--details", type=Path, help="write one JSON line per question with the prediction")
    ap.add_argument("--allow-paid", action="store_true", help="run paid (vision) extraction for drawings not cached")
    ap.add_argument("--llm", action="store_true", help="map unrecognised questions with Gemini (needs GEMINI_API_KEY)")
    args = ap.parse_args(argv)

    if args.split == "heldout":
        print("Held-out run: use for deck numbers, not for tuning.", file=sys.stderr)
    print(report(run(args.questions, args.split, args.limit, args.details, args.allow_paid, args.llm)))


if __name__ == "__main__":
    main()
