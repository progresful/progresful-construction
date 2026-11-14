"""Routing by file type, running extraction once, caching one JSON per drawing."""

from __future__ import annotations

import re
from pathlib import Path

from .extractors import EXTRACTORS
from .schema import Drawing, Kind

CACHE_DIR = Path("cache")

RASTER_SUFFIXES = {".png", ".jpg", ".jpeg"}

# A vector PDF page has at least this many characters of real text.
# Below it, treat the page as a scan and send it to the raster extractor.
MIN_PDF_TEXT_CHARS = 20


def is_scanned_pdf(path: Path) -> bool:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        return all(
            len(page.get_textpage().get_text_range().strip()) < MIN_PDF_TEXT_CHARS
            for page in pdf
        )
    finally:
        pdf.close()


# Folders of large technical sheets (structural, piping, ...): read in tiles, not as floor-plan images.
SHEET_FOLDERS = {"challenge"}


def route(path: str | Path) -> Kind:
    path = Path(path)
    suffix = path.suffix.lower()
    if path.parent.name in SHEET_FOLDERS and suffix in RASTER_SUFFIXES:
        return "sheet"
    if suffix == ".ifc":
        return "ifc"
    if suffix == ".dxf":
        return "dxf"
    if suffix == ".pdf":
        return "raster" if is_scanned_pdf(path) else "pdf"
    if suffix in RASTER_SUFFIXES:
        return "raster"
    raise ValueError(f"Unsupported drawing type: {path}")


# Richest format first. Files with the same stem are the same drawing in another format.
PREFERENCE = [".ifc", ".dxf", ".pdf", ".png", ".jpg", ".jpeg"]


def best_source(path: str | Path) -> Path:
    """The richest file holding the same drawing as path.

    Swiss plans come as .pdf/.dxf/.png with one stem; ifc_models plans
    <model>_plan-<level>.pdf are rendered from <model>.ifc.
    """
    path = Path(path)
    stems = [path.stem]
    if "_plan-" in path.stem:
        stems.append(path.stem.split("_plan-")[0])
    for suffix in PREFERENCE:
        for stem in stems:
            candidate = path.with_name(stem + suffix)
            if candidate.exists():
                return candidate
    return path


def cache_path(drawing: str | Path) -> Path:
    # Keyed on parent folder + file name of the resolved path, so "a.png", "./a.png" and an
    # absolute path share one cache file, and moving the data root does not invalidate it.
    parts = Path(drawing).resolve().parts[-2:]
    flat = re.sub(r"[^\w.-]+", "_", "__".join(parts))
    return CACHE_DIR / f"{flat}.json"


def load_cached(drawing: str | Path) -> Drawing | None:
    path = cache_path(drawing)
    return Drawing.load(path) if path.exists() else None


def ensure_extracted(drawing: str | Path, allow_raster: bool = False) -> Drawing:
    """Return the cached drawing, extracting it if missing or made by an older extractor.

    Paid extraction (vision calls; an extractor with PAID = True) only runs, or reruns on a
    stale cache, when allow_raster is set. The drawing is read from its richest copy (best_source).
    """
    drawing = best_source(drawing)
    kind = route(drawing)
    extractor = EXTRACTORS[kind]
    cached = load_cached(drawing)
    paid = getattr(extractor, "PAID", False)
    if cached is not None:
        fresh = cached.extractor_version == extractor.VERSION
        if fresh or (paid and not allow_raster):
            return cached
    if cached is None and paid and not allow_raster:
        raise RuntimeError(f"{drawing} is not extracted and paid extraction is not allowed")

    result = extractor.extract(Path(drawing))
    result.save(cache_path(drawing))
    return result
