"""The cached drawing file and the answer, shared by every extractor, the app and the batch runner.

See SPEC.md, "Data formats".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Kind = Literal["ifc", "dxf", "pdf", "raster", "sheet"]  # sheet: large technical sheets, read in tiles
Unit = Literal["count", "m2", "m3", "m", "text"]
# scale: an image plan's pixels converted with an estimated scale (see Drawing.scale).
# model_geometry: computed from an IFC model's own exact shapes (deterministic, so exact).
# reviewer: from an outline a reviewer drew (a reshaped room).
QuantitySource = Literal["quantity_set", "property", "geometry", "model_geometry", "label", "scale", "reviewer"]

# Raster confidence bands. Tuned on the train split only.
CONFIRMED_CONF = 0.8
UNCERTAIN_CONF = 0.4


@dataclass
class Element:
    id: int
    type: str  # window, door, room, wc, sink, shower, bathtub, label, ...
    source: str  # IFC GlobalId, DXF handle, PDF ref, or script / vlm / script+vlm
    exact: bool
    conf: float = 1.0
    bbox: list[float] | None = None  # [x0, y0, x1, y1] in drawing coordinates
    polygon: list[list[float]] | None = None
    room_type: str | None = None  # normalised type (bedroom, sauna, ...) for CubiCasa
    label: str | None = None  # name as written on the drawing or in the model
    number: str | None = None  # room number, e.g. "2.13"
    apartment: str | None = None  # apartment letter, e.g. "A"
    outdoor: bool | None = None  # balcony, loggia, terrace
    # area_m2, length_m, side_area_m2, volume_m3. Only filled where the file has real units.
    quantities: dict[str, float] | None = None
    # Per quantity: quantity_set or property (read from the file), label (printed on the drawing),
    # geometry (computed).
    quantity_source: dict[str, QuantitySource] | None = None
    storey: str | None = None
    page: int | None = None
    # Doors: how the leaf moves, in drawing coordinates. hinge, open (leaf tip when open) and closed
    # (leaf tip when shut, across the opening) are points; into is the id of the room the door opens
    # into (None: outside or unknown); exact says whether it was read from the file.
    swing: dict | None = None
    # Windows: which way the glass looks out. normal is the outward unit vector in drawing
    # coordinates; sheet is top/bottom/left/right of the sheet; compass is N, NE, ... when the
    # drawing gives north; room is the id of the room the window lights.
    facing: dict | None = None

    @property
    def band(self) -> Literal["confirmed", "uncertain", "dropped"]:
        if self.conf >= CONFIRMED_CONF:
            return "confirmed"
        if self.conf >= UNCERTAIN_CONF:
            return "uncertain"
        return "dropped"


@dataclass
class Drawing:
    drawing: str
    kind: Kind
    extractor_version: str
    units: str  # px, pt, mm, m, ... ; "unknown" when a DXF has $INSUNITS unset
    elements: list[Element] = field(default_factory=list)
    rotation: int = 0  # raster only: degrees clockwise applied to make the text upright
    mirrored: bool = False  # raster only: flipped left-right (after rotation) to make the text read
    # Raster only: the upright copy the elements' coordinates refer to; the app is served this image.
    plan_image: str | None = None
    extraction_cost_usd: float = 0.0
    # Element types the extractor looked for. None means all (structured files). Counting a type
    # outside this list is unanswerable, not zero.
    covers: list[str] | None = None
    # Whole-image counts from the vision model, keyed like templates.COUNT_KEYS ("windows": 3).
    # Used only for types not in `covers`: an estimate with no marks on the plan.
    counts: dict[str, int] | None = None
    # Image plans: metres per pixel and how it was found ("printed areas" or "door width"), the number
    # of rooms or doors it rests on, and its relative error on areas. None when it could not be found.
    scale: dict | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, d: dict) -> Drawing:
        d = dict(d)
        d["elements"] = [Element(**e) for e in d.get("elements", [])]
        return cls(**d)

    @classmethod
    def load(cls, path: str | Path) -> Drawing:
        return cls.from_dict(json.loads(Path(path).read_text()))

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.to_json())


@dataclass
class Answer:
    template: str | None
    value: float | int | str | None
    unit: Unit | None
    exact: bool
    params: dict = field(default_factory=dict)
    range: list[float] | None = None
    evidence_ids: list[int] = field(default_factory=list)
    uncertain_ids: list[int] = field(default_factory=list)
    cost_usd: float = 0.0
    fallback: bool = False

    @classmethod
    def cannot_answer(cls, cost_usd: float = 0.0) -> Answer:
        return cls(template=None, value=None, unit=None, exact=False, cost_usd=cost_usd)

    @property
    def answered(self) -> bool:
        return self.value is not None

    def to_dict(self) -> dict:
        return asdict(self)
