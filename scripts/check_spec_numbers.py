"""Step 0: check the numbers SPEC.md quotes from the challenge page against the downloaded preview.

    uv run python scripts/check_spec_numbers.py data/preview/questions.jsonl
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constructor.batch import FIELDS, load_questions, tier_of  # noqa: E402
from constructor.split import split_of  # noqa: E402

SUFFIX_KIND = {".ifc": "ifc", ".dxf": "dxf", ".pdf": "pdf", ".png": "raster", ".jpg": "raster", ".jpeg": "raster"}
CLAIMED = {"questions": 7990, "ifc_share": 0.16, "dxf_share": 0.30}


def main() -> int:
    rows = load_questions(Path(sys.argv[1]))
    kinds = Counter(SUFFIX_KIND.get(Path(r[FIELDS["drawing"]]).suffix.lower(), "?") for r in rows)
    drawings = {r[FIELDS["drawing"]] for r in rows}
    heldout = sum(split_of(d) == "heldout" for d in drawings)
    n = len(rows)

    print(f"questions: {n} (spec says {CLAIMED['questions']})")
    for kind, c in kinds.most_common():
        claim = CLAIMED.get(f"{kind}_share")
        print(f"  {kind:<7} {c:>6} {c / n:>6.1%}" + (f"  (spec says {claim:.0%})" if claim else ""))
    print(f"drawings: {len(drawings)}, held out: {heldout} ({heldout / max(len(drawings), 1):.1%})")
    print(f"fields in first row: {sorted(rows[0])}")
    tiers = Counter(tier_of(r[FIELDS["drawing"]]) for r in rows)
    print(f"tiers: {dict(tiers)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
