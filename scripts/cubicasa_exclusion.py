"""List CubiCasa5K plans that appear in Stoa's dataset, so training never touches them.

Stoa names raster drawings <tier>-<id>.png (e.g. colorful-11397.png); CubiCasa5K stores
them as <tier>/<id>/. IDs are excluded across all tiers to be safe.

    uv run python scripts/cubicasa_exclusion.py data/preview data/full > excluded_ids.txt

Every training or few-shot loader must call is_excluded() on each CubiCasa5K plan.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

NAME = re.compile(r"^(high_quality_architectural|high_quality|colorful)-(\d+)\.(png|jpe?g)$", re.I)
EXCLUSION_FILE = Path(__file__).resolve().parent.parent / "excluded_ids.txt"


def stoa_ids(roots: list[Path]) -> set[str]:
    ids = set()
    for root in roots:
        for p in root.rglob("*"):
            m = NAME.match(p.name)
            if m:
                ids.add(m.group(2))
    return ids


def is_excluded(cubicasa_plan_dir: Path, excluded: set[str] | None = None) -> bool:
    if excluded is None:
        if not EXCLUSION_FILE.exists():
            raise RuntimeError("excluded_ids.txt missing: run scripts/cubicasa_exclusion.py first")
        excluded = set(EXCLUSION_FILE.read_text().split())
    return Path(cubicasa_plan_dir).name in excluded


def main() -> int:
    roots = [Path(a) for a in sys.argv[1:]]
    if not roots:
        print(__doc__, file=sys.stderr)
        return 2
    ids = stoa_ids(roots)
    if not ids:
        # An empty list would silently allow everything; fail loudly instead.
        print("No Stoa raster files matched <tier>-<id>.png; check the naming.", file=sys.stderr)
        return 1
    print("\n".join(sorted(ids, key=int)))
    print(f"{len(ids)} CubiCasa5K plan IDs excluded", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
