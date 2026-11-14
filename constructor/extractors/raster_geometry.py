"""Plan geometry from pixels, free and fast (no model calls).

- walls: the thickest strokes on the plan (distance transform, then a morphological opening);
- openings: gaps along a wall's line, found by closing the wall mask along each axis. Used to
  seal rooms; not counted as windows or doors (that lost to the whole-image count, SPEC.md step 8);
- room regions: the free space around a room label, with walls (thin ones included) and every
  opening and doorway sealed.

Coordinates are image pixels. Fitted on the train split only.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

INK_MAX = 120  # a pixel is ink when its darkest channel is below this (coloured walls count, pale fills do not)
WALL_SHARE = 0.15  # walls are the thickest 15% of stroke ridges
THIN_LINE_PLAN = 0.01  # thick-wall mask below this share of the image: a thin-line plan
OPENING_SPAN = 0.18  # longest opening, as a share of the plan's span


@dataclass
class Opening:
    bbox: list[int]  # x0, y0, x1, y1
    horizontal: bool


def ink_mask(image) -> np.ndarray:
    return (image.min(axis=2) < INK_MAX).astype(np.uint8)


def wall_mask(image) -> tuple[np.ndarray, int]:
    """Thick-stroke mask and the kernel size used (about one wall thickness)."""
    ink = ink_mask(image)
    dt = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    ridge = dt[(dt == cv2.dilate(dt, np.ones((3, 3)))) & (dt >= 1)]
    if ridge.size == 0:
        return np.zeros_like(ink), 3
    hist = np.bincount(np.round(ridge).astype(int))
    share_at_least = np.cumsum(hist[::-1])[::-1] / hist.sum()
    half = max(2, int(np.argmax(share_at_least < WALL_SHARE)))
    k = max(3, int(half * 1.4))
    return cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))), k


def wall_strokes(image, wall: np.ndarray, k: int) -> np.ndarray:
    """Walls, thin ones included: strokes thicker than text and furniture lines. On thin-line plans
    (scans, pen drawings) walls are no thicker than text, so all ink is used; rooms grow around the
    letters and furniture."""
    ink = ink_mask(image)
    if wall.mean() < THIN_LINE_PLAN:
        return ink
    t = max(2, k // 2)
    return cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (t, t))) | wall


def openings(wall: np.ndarray, k: int) -> list[Opening]:
    ys, xs = np.nonzero(wall)
    if len(xs) == 0:
        return []
    span = max(xs.max() - xs.min(), ys.max() - ys.min())
    length = max(3, int(span * OPENING_SPAN))
    found: list[Opening] = []
    for horizontal in (True, False):
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1) if horizontal else (1, length))
        gap = (cv2.morphologyEx(wall, cv2.MORPH_CLOSE, kernel) > 0) & (wall == 0)
        n, _, stats, _ = cv2.connectedComponentsWithStats(gap.astype(np.uint8))
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            along, across = (w, h) if horizontal else (h, w)
            # As long as a narrow door at least, about as thick as the wall, and mostly solid.
            if along >= 1.5 * k and 0.5 * k <= across <= 3 * k and area >= 0.5 * w * h:
                found.append(Opening([int(x), int(y), int(x + w), int(y + h)], horizontal))
    return found


def _barriers(image, wall: np.ndarray, k: int, sealed_openings: list[Opening]) -> np.ndarray:
    """Walls (thin ones included) with every opening and doorway sealed."""
    barriers = wall_strokes(image, wall, k)
    for o in sealed_openings:
        x0, y0, x1, y1 = o.bbox
        barriers[y0:y1, x0:x1] = 1
    # Doorways in thin walls are not openings of the thick-wall mask. Seal only gaps about as thick
    # as a wall: a raw closing would also fill every room narrower than the closing length.
    for o in openings(barriers, max(3, k // 2)):
        x0, y0, x1, y1 = o.bbox
        barriers[y0:y1, x0:x1] = 1
    barriers = cv2.dilate(barriers, np.ones((3, 3), np.uint8))

    return barriers


@dataclass
class Region:
    polygon: list[list[int]]
    bbox: list[int]


WORK_SIDE = 600  # region growing runs on a copy scaled to this size
PLAN_GAP = 0.06  # wall pieces closer than this share of the image belong to one plan
MIN_PLAN_SHARE = 0.2  # a wall group with less than this share of the largest group's walls is not a plan


def _doorway_edge(wall: np.ndarray, box: list[float]):
    """For a door whose swing is unknown: the side of its box that spans the opening, i.e. the one
    the wall carries on past at both ends. None if no side looks like that."""
    x0, y0, x1, y1 = box
    h, w = wall.shape
    reach = max(3, int(0.15 * max(x1 - x0, y1 - y0)))

    def wall_at(x, y):
        xi, yi = int(round(x)), int(round(y))
        return 0 <= xi < w and 0 <= yi < h and bool(wall[max(0, yi - 2) : yi + 3, max(0, xi - 2) : xi + 3].any())

    sides = [((x0, y0), (x1, y0), (1, 0)), ((x0, y1), (x1, y1), (1, 0)), ((x0, y0), (x0, y1), (0, 1)), ((x1, y0), (x1, y1), (0, 1))]
    best, best_score = None, 0
    for a, b, (dx, dy) in sides:
        score = wall_at(a[0] - dx * reach, a[1] - dy * reach) + wall_at(b[0] + dx * reach, b[1] + dy * reach)
        if score > best_score:
            best, best_score = (a, b), score
    return best if best_score == 2 else None


NECK_SHARE = 0.025  # openings narrower than this share of the plan are cut from a room's fill
POLY_EPSILON = 0.0025  # outline simplification, as a share of the plan's size


def label_regions(image, wall: np.ndarray, k: int, sealed: list[Opening], points: list[tuple[float, float]],
                  doors: list | None = None, windows: list | None = None, limits: list | None = None) -> list[Region | None]:
    """Split the building's free space between the labels: every label grows through free space at
    the same speed and each pixel goes to the label that reaches it first. Walls stop the growth;
    where a doorway leaks, the neighbouring label claims its own side. None for a label off the plan."""
    from collections import deque

    h, w = wall.shape
    scale = min(1.0, WORK_SIDE / max(h, w))
    sw, sh = max(1, int(w * scale)), max(1, int(h * scale))
    barriers = cv2.resize(_barriers(image, wall, k, sealed), (sw, sh), interpolation=cv2.INTER_NEAREST)
    # Windows are wall as far as rooms go: thin glazing lines would let a balcony's fill in.
    for x0, y0, x1, y1 in windows or []:
        cv2.rectangle(barriers, (int(x0 * scale), int(y0 * scale)), (int(x1 * scale), int(y1 * scale)), 1, -1)
    # Shut every door: a line from the hinge across the opening, or along the wall side of its box
    # when the swing is unknown. Door gaps are not wall-thick, so without this one room's fill runs into the next.
    for d in doors or []:
        if len(d) == 2:
            (hx, hy), (cx, cy) = d
            # Reach a little past both ends, into the jambs.
            dx, dy = (cx - hx) * 0.08, (cy - hy) * 0.08
            cv2.line(barriers, (int((hx - dx) * scale), int((hy - dy) * scale)), (int((cx + dx) * scale), int((cy + dy) * scale)), 1, 2)
        elif (edge := _doorway_edge(wall, d)) is not None:
            (ax, ay), (bx, by) = edge
            cv2.line(barriers, (int(ax * scale), int(ay * scale)), (int(bx * scale), int(by * scale)), 1, 2)
    # The building outline: wall pieces are grouped across window-sized gaps, and each group big
    # enough to be a plan (an image may hold several floors) contributes its own hull. Notes,
    # legends and title blocks form small groups and are left out.
    # All wall-like strokes, not only the thickest: some CAD styles draw walls as two thin lines.
    strokes = wall_strokes(image, wall, k)
    small_wall = cv2.resize(strokes, (sw, sh), interpolation=cv2.INTER_NEAREST)
    bridge = max(5, int(max(sw, sh) * PLAN_GAP))
    n, comp, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(small_wall, np.ones((bridge, bridge), np.uint8)))
    footprint = np.zeros((sh, sw), np.uint8)
    if n > 1:
        wall_px = [int(small_wall[comp == i].sum()) for i in range(1, n)]
        keep = [i for i, px in enumerate(wall_px, 1) if px >= MIN_PLAN_SHARE * max(wall_px)]
        # One hull over all plan-sized groups: window gaps split an outer wall into several groups,
        # and a hull per group cuts rooms along its diagonals.
        # Small wall pieces inside the plan's extent belong to it too: windows cut an outer wall into
        # short pieces, and leaving one out makes the outline cut across a room's corner.
        ys_k, xs_k = np.nonzero(np.isin(comp, keep))
        pad = int(max(sw, sh) * 0.02)
        bx0, bx1, by0, by1 = xs_k.min() - pad, xs_k.max() + pad, ys_k.min() - pad, ys_k.max() + pad
        for i in range(1, n):
            if i not in keep:
                x, y, cw, ch = stats[i, :4]
                if x >= bx0 and y >= by0 and x + cw <= bx1 and y + ch <= by1:
                    keep.append(i)
        ys, xs = np.nonzero(small_wall & np.isin(comp, keep))
        cv2.fillPoly(footprint, [cv2.convexHull(np.stack([xs, ys], axis=1).astype(np.int32))], 1)
    free = (barriers == 0) & (footprint > 0)

    owner = np.full((sh, sw), -1, np.int32)
    queue: deque = deque()
    for i, (x, y) in enumerate(points):
        cx, cy = int(x * scale), int(y * scale)
        # Label text and furniture are ink: start from the free pixels around the label, widening
        # the search until some are found.
        for share in (0.015, 0.03, 0.06):
            r = max(2, int(max(sw, sh) * share))
            y0, y1, x0, x1 = max(0, cy - r), min(sh, cy + r + 1), max(0, cx - r), min(sw, cx + r + 1)
            seeds = [(y0 + yy, x0 + xx) for yy, xx in zip(*np.nonzero(free[y0:y1, x0:x1])) if owner[y0 + yy, x0 + xx] == -1]
            if seeds:
                break
        for yy, xx in seeds:
            owner[yy, xx] = i
            queue.append((yy, xx))
    # Each room's extent, if known (work scale, a little margin): its fill may not leave it.
    lim = [None] * len(points)
    for i, b in enumerate(limits or []):
        if b is not None and i < len(points):
            m = 0.015 * max(sw, sh)
            lim[i] = (b[0] * scale - m, b[1] * scale - m, b[2] * scale + m, b[3] * scale + m)
    while queue:
        y, x = queue.popleft()
        i = owner[y, x]
        box = lim[i]
        for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if box is not None and not (box[0] <= nx <= box[2] and box[1] <= ny <= box[3]):
                continue
            if 0 <= ny < sh and 0 <= nx < sw and free[ny, nx] and owner[ny, nx] == -1:
                owner[ny, nx] = i
                queue.append((ny, nx))

    out: list[Region | None] = []
    for i in range(len(points)):
        mask = (owner == i).astype(np.uint8)
        if mask.sum() < 4:
            out.append(None)
            continue
        # Cut thin necks (leaks through gaps that were not sealed) and keep the room's main body.
        neck = max(3, int(max(sw, sh) * NECK_SHARE))
        opened = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (neck, neck)))
        if opened.sum() >= 0.5 * mask.sum():
            mask = opened
        n_c, comp_c, stats_c, _ = cv2.connectedComponentsWithStats(mask)
        if n_c > 2:
            mask = (comp_c == 1 + int(np.argmax(stats_c[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contour = max(contours, key=cv2.contourArea)
        poly = (cv2.approxPolyDP(contour, POLY_EPSILON * (sw + sh), True).reshape(-1, 2) / scale).astype(int)
        bx, by, bw, bh = cv2.boundingRect(poly)
        out.append(Region(poly.tolist(), [bx, by, bx + bw, by + bh]))
    return out


# --- door swings and window facing ---------------------------------------------------------

SWING_MIN_SCORE = 0.45  # share of the quarter arc that must be inked to call a hinge
SWING_MARGIN = 0.15  # and by how much it must beat the next-best corner


def _inked(ink: np.ndarray, x: float, y: float, r: int = 2) -> bool:
    h, w = ink.shape
    xi, yi = int(round(x)), int(round(y))
    if not (0 <= xi < w and 0 <= yi < h):
        return False
    return bool(ink[max(0, yi - r) : yi + r + 1, max(0, xi - r) : xi + r + 1].any())


def door_swing(ink: np.ndarray, bbox: list[float]) -> dict | None:
    """Read a door symbol: a quarter arc centred on the hinge, the leaf drawn straight from the
    hinge. Tries each corner of the box as the hinge and keeps the one whose quarter arc is inked.
    Returns {"hinge", "open", "closed"} points in pixels, or None for symbols that are not a single
    swing (double, sliding and folding doors)."""
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    if w < 6 or h < 6 or max(w, h) > 2.2 * min(w, h):
        return None
    r = (w + h) / 2
    tol = max(2, round(r * 0.04))
    corners = {(0, 0): (x0, y0), (1, 0): (x1, y0), (0, 1): (x0, y1), (1, 1): (x1, y1)}
    scores = {}
    for (cx, cy), (hx, hy) in corners.items():
        sx, sy = (1 if cx == 0 else -1), (1 if cy == 0 else -1)  # towards the box interior
        hits = 0
        n = 24
        for i in range(1, n):  # skip the two ends, which touch the leaf and the jamb
            a = (np.pi / 2) * i / n
            hits += _inked(ink, hx + sx * r * np.cos(a), hy + sy * r * np.sin(a), tol)
        scores[(cx, cy)] = hits / (n - 1)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (best, score), (_, second) = ranked[0], ranked[1]
    if score < SWING_MIN_SCORE or score - second < SWING_MARGIN:
        return None
    hx, hy = corners[best]
    sx, sy = (1 if best[0] == 0 else -1), (1 if best[1] == 0 else -1)
    # Of the two edges from the hinge, one is the leaf when open (it points into the room: empty
    # floor just past its tip) and one spans the opening when shut (the wall carries on past it).
    def ink_past(dx, dy):
        tip_x, tip_y = hx + dx * r, hy + dy * r
        return sum(_inked(ink, tip_x + dx * r * t / 10, tip_y + dy * r * t / 10, tol) for t in range(1, 4))

    past_x, past_y = ink_past(sx, 0), ink_past(0, sy)
    if past_x == past_y:
        return None
    if past_x > past_y:  # the wall carries on along x: the opening runs along x, the leaf along y
        open_pt, closed_pt = [hx, hy + sy * r], [hx + sx * r, hy]
    else:
        open_pt, closed_pt = [hx + sx * r, hy], [hx, hy + sy * r]
    rnd = lambda p: [round(p[0], 1), round(p[1], 1)]  # noqa: E731
    return {"hinge": rnd([hx, hy]), "open": rnd(open_pt), "closed": rnd(closed_pt), "exact": False}


def point_in(poly: list[list[float]], x: float, y: float) -> bool:
    inside = False
    for i in range(len(poly)):
        (ax, ay), (bx, by) = poly[i], poly[i - 1]
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


SHEET_SIDES = {(0, -1): "top", (0, 1): "bottom", (-1, 0): "left", (1, 0): "right"}


def window_facing(bbox: list[float], rooms: list[tuple[int, list[list[float]]]], footprint: list[list[float]] | None,
                  y_up: bool = False) -> dict | None:
    """Which way a window looks out: of the two sides across its glazing, the outside is the one
    not in any room (or outside the plan's footprint). Returns {"normal", "sheet", "room"}."""
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = x1 - x0, y1 - y0
    normals = [(0, -1), (0, 1)] if w >= h else [(-1, 0), (1, 0)]
    d = max(w, h) * 0.35 + min(w, h)

    def room_at(x, y):
        return next((rid for rid, poly in rooms if point_in(poly, x, y)), None)

    sides = []
    for nx, ny in normals:
        px, py = cx + nx * d, cy + ny * d
        rid = room_at(px, py)
        in_plan = footprint is not None and point_in(footprint, px, py)
        sides.append(((nx, ny), rid, in_plan))
    (n_a, room_a, plan_a), (n_b, room_b, plan_b) = sides
    if room_a is not None and room_b is None:
        out, room = n_b, room_a
    elif room_b is not None and room_a is None:
        out, room = n_a, room_b
    elif plan_a != plan_b:  # neither side in a labelled room: use the footprint
        out, room = (n_b, room_a) if plan_a else (n_a, room_b)
    else:
        return None
    sheet = SHEET_SIDES[(out[0], -out[1]) if y_up else out]  # CAD y points up the sheet
    return {"normal": list(out), "sheet": sheet, "room": room}
