"""One extractor per kind. Each module exposes VERSION and extract(path) -> Drawing.

Bump VERSION whenever an extractor's output changes; ingest re-extracts stale caches.
"""

from . import dxf, ifc, pdf, raster, sheet

EXTRACTORS = {"ifc": ifc, "dxf": dxf, "pdf": pdf, "raster": raster, "sheet": sheet}
