"""Plan images for the app, in the same coordinates as the extracted elements.

DXF and IFC plans are drawn as SVG in drawing units with y up. The SVG viewBox is the
plan's viewbox and the content is flipped inside it, so the app maps an element point
(x, y) to the image with the API.md flip_y formula and the marks line up exactly.
"""

from __future__ import annotations

import html
import math
from pathlib import Path

from .schema import Drawing, Element

PAD = 1.0  # metres around the drawing


def _svg(viewbox: list[float], body: list[str], px_per_unit: float) -> str:
    x, y, w, h = viewbox
    # Map y -> 2y + h - y so that, in viewBox space, y_img = vy + vh - (y - vy).
    flip = f"translate(0,{2 * y + h:.4f}) scale(1,-1)"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x:.4f} {y:.4f} {w:.4f} {h:.4f}" '
        f'width="{w * px_per_unit:.0f}" height="{h * px_per_unit:.0f}">'
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#ffffff"/>'
        f'<g transform="{flip}" stroke-linejoin="round" stroke-linecap="round">{"".join(body)}</g></svg>'
    )


def _points(pts) -> str:
    return " ".join(f"{px:.4f},{py:.4f}" for px, py in pts)


def _text(x: float, y: float, s: str, size: float, weight: str = "normal") -> str:
    # Text is drawn upright: undo the global flip around its own anchor.
    return (
        f'<text transform="translate({x:.4f},{y:.4f}) scale(1,-1)" font-size="{size:.3f}" '
        f'font-family="Inter, Helvetica, Arial, sans-serif" font-weight="{weight}" fill="#333" '
        f'text-anchor="middle">{html.escape(s)}</text>'
    )


def bounds(points: list[tuple[float, float]]) -> list[float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs) - PAD, min(ys) - PAD, max(xs) - min(xs) + 2 * PAD, max(ys) - min(ys) + 2 * PAD]


# --- DXF -------------------------------------------------------------------------------

DXF_STYLE = {
    "WALL": 'fill="#6b6b6b" stroke="#444" stroke-width="0.02"',
    "WINDOW": 'fill="none" stroke="#4a7ab5" stroke-width="0.025"',
    "DOOR": 'fill="none" stroke="#8a6d3b" stroke-width="0.02"',
    "FIXTURE": 'fill="none" stroke="#555" stroke-width="0.015"',
    "ROOM_OUTLINE": 'fill="none" stroke="#c9d3df" stroke-width="0.02"',
    # Solid: in the app, dashed marks mean "uncertain".
    "UNIT_OUTLINE": 'fill="none" stroke="#9b59b6" stroke-width="0.025" stroke-opacity="0.6"',
}


def dxf_svg(path: Path) -> tuple[str, list[float]]:
    import ezdxf
    from ezdxf import path as dxfpath

    msp = ezdxf.readfile(str(path)).modelspace()
    body: list[str] = []
    extent: list[tuple[float, float]] = []
    for layer in ["ROOM_OUTLINE", "WALL", "WINDOW", "DOOR", "FIXTURE", "UNIT_OUTLINE"]:
        style = DXF_STYLE[layer]
        for e in msp.query(f"*[layer=='{layer}']"):
            kind = e.dxftype()
            if kind == "LWPOLYLINE":
                pts = [(p[0], p[1]) for p in e.get_points("xy")]
                extent += pts
                tag = "polygon" if e.closed else "polyline"
                fill = style if e.closed else style.replace('fill="#6b6b6b"', 'fill="none"')
                body.append(f'<{tag} points="{_points(pts)}" {fill}/>')
            elif kind == "HATCH":
                for p in dxfpath.from_hatch(e):
                    pts = [(v.x, v.y) for v in p.flattening(0.01)]
                    if len(pts) >= 3:
                        body.append(f'<polygon points="{_points(pts)}" {style}/>')
            elif kind == "LINE":
                s, t = e.dxf.start, e.dxf.end
                body.append(f'<line x1="{s.x}" y1="{s.y}" x2="{t.x}" y2="{t.y}" {style}/>')
            elif kind == "CIRCLE":
                c = e.dxf.center
                body.append(f'<circle cx="{c.x}" cy="{c.y}" r="{e.dxf.radius}" {style}/>')
            elif kind == "ARC":
                c, r = e.dxf.center, e.dxf.radius
                a0, a1 = math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)
                sweep = (a1 - a0) % (2 * math.pi)
                x0, y0 = c.x + r * math.cos(a0), c.y + r * math.sin(a0)
                x1, y1 = c.x + r * math.cos(a1), c.y + r * math.sin(a1)
                large = 1 if sweep > math.pi else 0
                body.append(f'<path d="M{x0:.4f},{y0:.4f} A{r:.4f},{r:.4f} 0 {large} 1 {x1:.4f},{y1:.4f}" {style}/>')
    for e in msp.query("TEXT[layer=='ROOM_TEXT']"):
        p = e.dxf.insert
        body.append(_text(p.x, p.y, e.dxf.text, e.dxf.height * 1.1))
    viewbox = bounds(extent) if extent else [0, 0, 10, 10]
    return _svg(viewbox, body, px_per_unit=60), viewbox


# --- IFC -------------------------------------------------------------------------------

IFC_STYLE = {
    "room": 'fill="#eef3f8" stroke="#b8c6d6" stroke-width="0.03"',
    "wall": 'fill="#6b6b6b" stroke="#444" stroke-width="0.02"',
    "column": 'fill="#444" stroke="#222" stroke-width="0.02"',
    "window": 'fill="#dbe8f6" stroke="#4a7ab5" stroke-width="0.03"',
    "door": 'fill="#f3e9d8" stroke="#8a6d3b" stroke-width="0.03"',
    "stair": 'fill="none" stroke="#777" stroke-width="0.03"',
}
IFC_ORDER = ["room", "stair", "wall", "column", "window", "door"]


def _outline(e: Element) -> list[tuple[float, float]] | None:
    if e.polygon:
        return [(p[0], p[1]) for p in e.polygon]
    if e.bbox:
        x0, y0, x1, y1 = e.bbox
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return None


def ifc_storey_viewbox(d: Drawing, storey: str) -> list[float] | None:
    pts = [p for e in d.elements if e.storey == storey and e.type in IFC_STYLE for p in (_outline(e) or [])]
    return bounds(pts) if pts else None


def ifc_svg(d: Drawing, storey: str) -> tuple[str, list[float]] | None:
    viewbox = ifc_storey_viewbox(d, storey)
    if viewbox is None:
        return None
    body: list[str] = []
    on_storey = [e for e in d.elements if e.storey == storey]
    for kind in IFC_ORDER:
        for e in on_storey:
            if e.type == kind and (pts := _outline(e)):
                body.append(f'<polygon points="{_points(pts)}" {IFC_STYLE[kind]}/>')
    for e in on_storey:
        if e.type == "room" and e.label and (pts := _outline(e)):
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            body.append(_text(cx, cy, e.label, 0.28))
    return _svg(viewbox, body, px_per_unit=40), viewbox
