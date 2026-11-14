"""Extract many drawings in parallel (the batch runner extracts one at a time).

    uv run python scripts/extract_all.py data/preview/junction-dataset-preview/questions.jsonl --source cubicasa5k --allow-paid
"""

from __future__ import annotations

import argparse
from functools import partial
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from constructor.batch import FIELDS, load_questions  # noqa: E402
from constructor.ingest import best_source, ensure_extracted  # noqa: E402

# ifcopenshell's geometry iterator segfaults when run from several threads at once.
IFC_LOCK = threading.Lock()


def extract_one(root: Path, allow_paid: bool, p: str) -> str | None:
    """Extract one drawing; an error message instead of raising. Top-level so processes can run it."""
    path = root / p
    try:
        if best_source(path).suffix.lower() == ".ifc":
            with IFC_LOCK:
                ensure_extracted(path, allow_raster=allow_paid)
        else:
            ensure_extracted(path, allow_raster=allow_paid)
        return None
    except Exception as e:
        return f"{p}: {type(e).__name__}: {e}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", type=Path)
    ap.add_argument("--source", help="only drawings under data/<source>/")
    ap.add_argument("--allow-paid", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--sample", type=int, help="only a fixed random sample of this many drawings (same every run)")
    args = ap.parse_args()
    paths = sorted({r[FIELDS["drawing"]] for r in load_questions(args.questions)})
    if args.source:
        paths = [p for p in paths if p.startswith(f"data/{args.source}/")]
    if args.sample and args.sample < len(paths):
        import random

        paths = sorted(random.Random(2026).sample(paths, args.sample))

    run = partial(extract_one, args.questions.parent, args.allow_paid)

    start = time.time()
    # CAD reading (ezdxf) is not thread-safe: several plans at once in threads fail with odd
    # TypeErrors. Swiss plans run in processes; image plans (network-bound) stay in threads.
    pool_class = ProcessPoolExecutor if args.source == "swiss_dwellings" else ThreadPoolExecutor
    with pool_class(args.workers) as pool:
        errors = []
        for i, e in enumerate(pool.map(run, paths), 1):
            if e:
                errors.append(e)
            if i % 50 == 0:
                print(f"  {i}/{len(paths)} in {time.time() - start:.0f}s", flush=True)
    print(f"{len(paths) - len(errors)} extracted, {len(errors)} failed")
    for e in errors[:10]:
        print("  ", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
