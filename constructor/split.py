"""Train / held-out split by drawing group, fixed by a hash.

Run this before anyone reads the questions. Templates, dictionaries, prompts and
thresholds are designed on train only.

Copies of one drawing must share a side, or the held-out set leaks:
- the same stem in another format (swiss_dwellings .pdf/.dxf/.png) is the same drawing;
- ifc_models plans <model>_plan-<level>.pdf are rendered from <model>.ifc;
- opening_design sheets of one project share a building.
"""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from typing import Literal

HELDOUT_FRACTION = 0.2

Split = Literal["train", "heldout"]


def group_of(path: str) -> str:
    p = PurePosixPath(path.replace("\\", "/"))
    parts = p.parts
    # The source folder sits under the *last* "data" directory: paths may be relative to the dataset
    # ("data/swiss_dwellings/x.pdf") or full ("data/preview/<dataset>/data/swiss_dwellings/x.pdf").
    data_dirs = [i for i, part in enumerate(parts[:-1]) if part == "data"]
    source = parts[data_dirs[-1] + 1] if data_dirs else (parts[-2] if len(parts) > 1 else "")
    if source == "opening_design":
        return f"opening_design/{parts[parts.index('opening_design') + 1]}"
    stem = p.stem
    if source == "ifc_models":
        stem = stem.split("_plan-")[0]
    return f"{source}/{stem}"


def split_of(path: str) -> Split:
    bucket = int(hashlib.sha256(group_of(path).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "heldout" if bucket < HELDOUT_FRACTION else "train"
