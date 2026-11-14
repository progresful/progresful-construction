"""Fail if any installed dependency is AGPL or GPL (LGPL is fine). Run in CI and before submission.

    uv run python scripts/license_check.py
"""

from __future__ import annotations

import re
import sys
from importlib.metadata import distributions

# Known offenders, caught by name even when their metadata is vague.
BANNED = {"pymupdf": "AGPL", "fitz": "AGPL", "ultralytics": "AGPL"}

COPYLEFT = re.compile(r"\bA?GPL\b|GNU (Affero )?General Public", re.I)
LESSER = re.compile(r"\bLGPL\b|Lesser General Public|Library General Public", re.I)


def licence_text(dist) -> str:
    meta = dist.metadata
    parts = [meta.get("License-Expression") or "", (meta.get("License") or "")[:200]]
    parts += [c for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return " | ".join(p for p in parts if p)


def main() -> int:
    bad = []
    for dist in distributions():
        name = (dist.metadata.get("Name") or "").lower()
        text = licence_text(dist)
        if name in BANNED:
            bad.append((name, BANNED[name]))
        elif COPYLEFT.search(LESSER.sub("", text)):
            bad.append((name, text))
    for name, text in sorted(bad):
        print(f"COPYLEFT  {name}: {text}")
    if bad:
        print(f"\n{len(bad)} copyleft dependencies. Shipped code must be MIT-compatible.")
        return 1
    print("OK: no AGPL or GPL dependencies installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
