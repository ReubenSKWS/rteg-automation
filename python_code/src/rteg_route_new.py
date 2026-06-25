"""
New routing pipeline (steps 5+), built fresh on top of the step-4 frame state.

Core principle: **do not compute intercepts — read them from the die.** The
filter ``connectMTE`` / ``connectMBE`` polygons already touch the resonator body
at the true collar contact. Step 4.1 copies those onto the frame. This module:

1. keeps only the connect piece(s) that actually bridge the resonator body
   (orphan filter metal that never touches the body is dropped);
2. reads the two collar intercepts as the contact corners of ``connect ∩ body``;
3. draws a pad-side connector from the signal pad TR/BR corners to the connect
   finger's pad-facing edge and unions it with the finger, so the collar contact
   (and therefore the intercepts) is never modified;
4. handles the ground filler with the same contact logic;
5. can shift the resonator (up/down/left/right) when the signal route overlaps
   the body or forms an acute angle, then re-derives the route.

Targets first three KB331 resonators: index 1 (P1A, center_pad / MTE signal),
index 2 (S1B, collar_extend / MBE signal), index 6 (S3, center_pad / MTE signal).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import gdstk

from layermap import LayerMap
from rteg_utils import polys_bbox

Point = tuple[float, float]
Bbox = tuple[Point, Point]


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _poly_points(poly: gdstk.Polygon) -> list[Point]:
    return [(float(x), float(y)) for x, y in poly.points]


def _overlap_area(
    a: Sequence[gdstk.Polygon] | gdstk.Polygon,
    b: Sequence[gdstk.Polygon] | gdstk.Polygon,
    *,
    precision: float = 1e-3,
) -> float:
    inter = gdstk.boolean(a, b, "and", precision=precision)
    return sum(abs(p.area()) for p in inter) if inter else 0.0


def _point_on_boundary(point: Point, poly: gdstk.Polygon, tol: float) -> bool:
    pts = _poly_points(poly)
    n = len(pts)
    px, py = point
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        ll = dx * dx + dy * dy
        if ll < 1e-18:
            if math.hypot(px - x0, py - y0) <= tol:
                return True
            continue
        t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / ll))
        qx, qy = x0 + t * dx, y0 + t * dy
        if math.hypot(px - qx, py - qy) <= tol:
            return True
    return False


def _point_on_any_boundary(
    point: Point, polys: Sequence[gdstk.Polygon], tol: float
) -> bool:
    return any(_point_on_boundary(point, p, tol) for p in polys)


def _dedupe(points: Sequence[Point], tol: float) -> list[Point]:
    out: list[Point] = []
    for pt in points:
        if not any(_dist(pt, q) <= tol for q in out):
            out.append(pt)
    return out


def _farthest_pair(points: Sequence[Point]) -> tuple[Point, Point]:
    best = (points[0], points[1])
    best_len = _dist(*best)
    for i, a in enumerate(points):
        for b in points[i + 1 :]:
            d = _dist(a, b)
            if d > best_len:
                best_len, best = d, (a, b)
    return best


def _order_by_y(a: Point, b: Point) -> tuple[Point, Point]:
    """Return ``(high_y, low_y)``; tie-break on larger X first."""
    if a[1] > b[1] + 1e-9:
        return a, b
    if b[1] > a[1] + 1e-9:
        return b, a
    return (a, b) if a[0] >= b[0] else (b, a)


def _signed_area(points: Sequence[Point]) -> float:
    s = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def _min_interior_angle_deg(points: Sequence[Point]) -> float:
    """Smallest interior angle of a simple polygon ring (degrees)."""
    pts = _dedupe(list(points), 1e-6)
    n = len(pts)
    if n < 3:
        return 180.0
    worst = 180.0
    for i in range(n):
        p0 = pts[(i - 1) % n]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        v1 = (p0[0] - p1[0], p0[1] - p1[1])
        v2 = (p2[0] - p1[0], p2[1] - p1[1])
        l1 = math.hypot(*v1)
        l2 = math.hypot(*v2)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
        worst = min(worst, math.degrees(math.acos(cos)))
    return worst


# --------------------------------------------------------------------------- #
# Step 5 — intercept extraction (read from die)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CollarContact:
    """Collar contact read from ``connect ∩ body`` for one signal terminal."""

    intercept_a: Point  # higher-Y mouth corner
    intercept_b: Point  # lower-Y mouth corner
    bridging: tuple[gdstk.Polygon, ...]  # connect pieces that touch the body
    orphans: tuple[gdstk.Polygon, ...]  # connect pieces that never touch the body
    overlap_area_um2: float

    @property
    def mouth_center(self) -> Point:
        return (
            (self.intercept_a[0] + self.intercept_b[0]) / 2.0,
            (self.intercept_a[1] + self.intercept_b[1]) / 2.0,
        )


def split_bridging_orphans(
    connect_polys: Sequence[gdstk.Polygon],
    body_polys: Sequence[gdstk.Polygon],
    *,
    precision: float = 1e-3,
    min_overlap_um2: float = 0.1,
) -> tuple[list[gdstk.Polygon], list[gdstk.Polygon]]:
    """Split connect metal into pieces that touch the body and orphans that don't."""
    bridging: list[gdstk.Polygon] = []
    orphans: list[gdstk.Polygon] = []
    for p in connect_polys:
        if _overlap_area(p, body_polys, precision=precision) >= min_overlap_um2:
            bridging.append(p)
        else:
            orphans.append(p)
    return bridging, orphans


def _cluster_touching(
    polys: Sequence[gdstk.Polygon],
    *,
    precision: float = 1e-3,
    min_overlap_um2: float = 0.01,
) -> list[list[gdstk.Polygon]]:
    """Group polygons that boolean-touch (transitively) into collar clusters."""
    clusters: list[list[gdstk.Polygon]] = []
    for p in polys:
        placed = False
        for cl in clusters:
            if any(_overlap_area(p, q, precision=precision) >= min_overlap_um2 for q in cl):
                cl.append(p)
                placed = True
                break
        if not placed:
            clusters.append([p])
    # Second pass to merge clusters that became connected.
    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                if any(
                    _overlap_area(a, b, precision=precision) >= min_overlap_um2
                    for a in clusters[i]
                    for b in clusters[j]
                ):
                    clusters[i].extend(clusters[j])
                    del clusters[j]
                    merged = True
                    break
            if merged:
                break
    return clusters


def _contact_for_cluster(
    bridging: Sequence[gdstk.Polygon],
    body_polys: Sequence[gdstk.Polygon],
    orphans: Sequence[gdstk.Polygon],
    *,
    precision: float,
    boundary_tol_um: float,
) -> CollarContact | None:
    overlap = gdstk.boolean(bridging, body_polys, "and", precision=precision)
    if not overlap:
        return None
    overlap_area = sum(abs(p.area()) for p in overlap)

    triple: list[Point] = []
    for piece in overlap:
        for v in _poly_points(piece):
            if _point_on_any_boundary(v, bridging, boundary_tol_um) and (
                _point_on_any_boundary(v, body_polys, boundary_tol_um)
            ):
                triple.append(v)
    candidates = _dedupe(triple, boundary_tol_um)
    if len(candidates) < 2:
        all_pts = [v for piece in overlap for v in _poly_points(piece)]
        candidates = _dedupe(all_pts, boundary_tol_um)
        if len(candidates) < 2:
            return None

    a, b = _farthest_pair(candidates)
    hi, lo = _order_by_y(a, b)
    return CollarContact(
        intercept_a=hi,
        intercept_b=lo,
        bridging=tuple(bridging),
        orphans=tuple(orphans),
        overlap_area_um2=overlap_area,
    )


def transitive_orphans(
    preserved_polys: Sequence[gdstk.Polygon],
    body_polys: Sequence[gdstk.Polygon],
    *,
    precision: float = 1e-3,
    min_overlap_um2: float = 0.05,
) -> list[gdstk.Polygon]:
    """
    Preserved filter-metal pieces not connected (transitively) to the body.

    A piece is kept if it touches the resonator body, or touches another kept
    piece. Everything else is an independent orphan to delete. Use per layer
    (MTE with body MTE, MBE with body MBE).
    """
    kept_idx: set[int] = set()
    for i, p in enumerate(preserved_polys):
        if _overlap_area(p, body_polys, precision=precision) >= min_overlap_um2:
            kept_idx.add(i)
    changed = True
    while changed:
        changed = False
        for i, p in enumerate(preserved_polys):
            if i in kept_idx:
                continue
            for j in kept_idx:
                if _overlap_area(p, preserved_polys[j], precision=precision) >= min_overlap_um2:
                    kept_idx.add(i)
                    changed = True
                    break
    return [p for i, p in enumerate(preserved_polys) if i not in kept_idx]


def extract_all_contacts(
    connect_polys: Sequence[gdstk.Polygon],
    body_polys: Sequence[gdstk.Polygon],
    *,
    precision: float = 1e-3,
    boundary_tol_um: float = 0.6,
    min_overlap_um2: float = 0.1,
) -> list[CollarContact]:
    """
    One ``CollarContact`` per distinct collar (cluster of touching connect metal).

    Orphan connect metal that never touches the body is recorded on every contact
    so callers can strip it regardless of which collar carries signal.
    """
    bridging, orphans = split_bridging_orphans(
        connect_polys, body_polys, precision=precision, min_overlap_um2=min_overlap_um2
    )
    if not bridging:
        return []
    contacts: list[CollarContact] = []
    for cluster in _cluster_touching(bridging, precision=precision):
        contact = _contact_for_cluster(
            cluster, body_polys, orphans,
            precision=precision, boundary_tol_um=boundary_tol_um,
        )
        if contact is not None:
            contacts.append(contact)
    return contacts


def select_signal_contact(
    contacts: Sequence[CollarContact],
    signal_pad_polys: Sequence[gdstk.Polygon],
) -> CollarContact | None:
    """Pick the collar whose mouth is closest to the signal pad center."""
    if not contacts:
        return None
    pad_bb = polys_bbox(list(signal_pad_polys))
    if pad_bb is None:
        return contacts[0]
    pc = ((pad_bb[0][0] + pad_bb[1][0]) / 2.0, (pad_bb[0][1] + pad_bb[1][1]) / 2.0)
    return min(contacts, key=lambda c: _dist(c.mouth_center, pc))


def extract_collar_contact(
    connect_polys: Sequence[gdstk.Polygon],
    body_polys: Sequence[gdstk.Polygon],
    *,
    signal_pad_polys: Sequence[gdstk.Polygon] | None = None,
    precision: float = 1e-3,
    boundary_tol_um: float = 0.6,
    min_overlap_um2: float = 0.1,
) -> CollarContact | None:
    """Signal collar contact: nearest-to-pad collar when several bridge the body."""
    contacts = extract_all_contacts(
        connect_polys, body_polys,
        precision=precision, boundary_tol_um=boundary_tol_um, min_overlap_um2=min_overlap_um2,
    )
    if not contacts:
        return None
    if signal_pad_polys is not None:
        return select_signal_contact(contacts, signal_pad_polys)
    return contacts[0]


# --------------------------------------------------------------------------- #
# Step 6 — signal route (pad → connect finger, collar untouched)
# --------------------------------------------------------------------------- #
def _signal_pad_bbox(signal_pad_polys: Sequence[gdstk.Polygon]) -> Bbox:
    bb = polys_bbox(list(signal_pad_polys))
    if bb is None:
        raise ValueError("signal pad has no geometry")
    return bb


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _launch_corners(
    launch_bbox: Bbox,
    a: Point,
    b: Point,
    mouth: Point,
    *,
    overlap_um: float,
    clamp_to_intercepts: bool = False,
) -> tuple[Point, Point]:
    """
    Two launch corners on the launch-bbox edge facing ``mouth`` (high-Y first).

    With ``clamp_to_intercepts`` the along-edge position is clamped to the
    intercept band so the connector is a narrow tab aligned to the collar mouth
    (right for the tall MBE filler). Otherwise the full facing edge is used
    (right for the GSG signal pad). Corners are biased ``overlap_um`` inward so
    the route overlaps the launch geometry for a clean boolean merge.
    """
    (x0, y0), (x1, y1) = launch_bbox
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    dx, dy = mouth[0] - cx, mouth[1] - cy
    if abs(dx) >= abs(dy):  # vertical facing edge
        xe = x1 if dx >= 0 else x0
        inward = -1.0 if dx >= 0 else 1.0
        if clamp_to_intercepts:
            ya, yb = _clamp(a[1], y0, y1), _clamp(b[1], y0, y1)
        else:
            ya, yb = y1, y0
        x = xe + inward * overlap_um
        return (x, max(ya, yb)), (x, min(ya, yb))
    # horizontal facing edge
    ye = y1 if dy >= 0 else y0
    inward = -1.0 if dy >= 0 else 1.0
    if clamp_to_intercepts:
        xa, xb = _clamp(a[0], x0, x1), _clamp(b[0], x0, x1)
    else:
        xa, xb = x1, x0
    y = ye + inward * overlap_um
    if a[1] >= b[1]:
        return (xa, y), (xb, y)
    return (xb, y), (xa, y)


def _nearest_ring_index(ring: Sequence[Point], point: Point) -> int:
    return min(range(len(ring)), key=lambda i: _dist(ring[i], point))


def _select_collar_body(
    body_polys: Sequence[gdstk.Polygon],
    a: Point,
    b: Point,
) -> gdstk.Polygon:
    """Body piece whose boundary best contains both intercepts."""
    def score(poly: gdstk.Polygon) -> float:
        ring = _poly_points(poly)
        if len(ring) < 3:
            return float("inf")
        da = min(_dist(ring[i], a) for i in range(len(ring)))
        db = min(_dist(ring[i], b) for i in range(len(ring)))
        return max(da, db)

    return min(body_polys, key=score)


def _arc_dist_to_polys(arc: Sequence[Point], polys: Sequence[gdstk.Polygon]) -> float:
    """Average distance from arc vertices to the nearest of ``polys`` (by vertex)."""
    targets = [pt for p in polys for pt in _poly_points(p)]
    if not targets or not arc:
        return float("inf")
    total = 0.0
    for v in arc:
        total += min(_dist(v, t) for t in targets)
    return total / len(arc)


def _collar_arc(
    body_poly: gdstk.Polygon,
    a: Point,
    b: Point,
    bridging: Sequence[gdstk.Polygon],
) -> list[Point]:
    """
    Walk the body boundary from ``a`` to ``b`` along the collar-mouth arc.

    Of the two boundary arcs between the intercepts, return the one that hugs the
    connect finger (the contact mouth), oriented ``a -> b`` inclusive of the body
    vertices nearest the intercepts.
    """
    ring = _poly_points(body_poly)
    n = len(ring)
    ia = _nearest_ring_index(ring, a)
    ib = _nearest_ring_index(ring, b)
    if ia == ib:
        return [ring[ia]]

    fwd: list[Point] = []
    i = ia
    while True:
        fwd.append(ring[i])
        if i == ib:
            break
        i = (i + 1) % n
    bwd: list[Point] = []
    i = ia
    while True:
        bwd.append(ring[i])
        if i == ib:
            break
        i = (i - 1) % n

    return fwd if _arc_dist_to_polys(fwd, bridging) <= _arc_dist_to_polys(bwd, bridging) else bwd


@dataclass
class SignalRoute:
    """Computed signal connector (pad → collar) for one resonator."""

    terminal: str  # "MTE" or "MBE"
    layer: int
    datatype: int
    connector: gdstk.Polygon  # pad → collar walk polygon (before union)
    net: gdstk.Polygon  # union(connector + bridging connect finger)
    contact: CollarContact
    pad_corners: tuple[Point, Point]
    arc_len: int
    min_angle_deg: float
    body_overlap_um2: float

    def is_clean(self, *, min_angle_deg: float, max_body_overlap_um2: float) -> bool:
        return (
            self.min_angle_deg >= min_angle_deg
            and self.body_overlap_um2 <= max_body_overlap_um2
        )


def build_signal_route(
    contact: CollarContact,
    launch_polys: Sequence[gdstk.Polygon],
    body_polys: Sequence[gdstk.Polygon],
    *,
    terminal: str,
    layer: int,
    datatype: int,
    merge_polys: Sequence[gdstk.Polygon] = (),
    launch_overlap_um: float = 0.5,
    clamp_launch: bool = False,
    precision: float = 1e-3,
) -> SignalRoute:
    """
    Build the signal route: launch-edge corners → intercept_a → collar boundary
    walk → intercept_b, then merge with the preexisting connect finger (and any
    ``merge_polys`` such as the MBE filler) into a single net polygon.

    ``launch_polys`` is the center GSG signal pad (MTE terminal, full edge) or
    the MBE rectangle filler (MBE terminal, ``clamp_launch`` for a narrow tab).
    The collar contact / intercepts are read from the die and used verbatim; the
    resonator-facing edge follows the body boundary between them.
    """
    launch_bbox = _signal_pad_bbox(launch_polys)
    mouth = contact.mouth_center
    launch_hi, launch_lo = _launch_corners(
        launch_bbox, contact.intercept_a, contact.intercept_b, mouth,
        overlap_um=launch_overlap_um, clamp_to_intercepts=clamp_launch,
    )

    collar_body = _select_collar_body(body_polys, contact.intercept_a, contact.intercept_b)
    arc = _collar_arc(
        collar_body, contact.intercept_a, contact.intercept_b, contact.bridging
    )

    # Ring: low launch corner → high launch corner → collar arc (a..b) → close.
    ring: list[Point] = [launch_lo, launch_hi, *arc]
    ring = _dedupe(ring, 0.05)
    if _signed_area(ring) < 0:
        ring = list(reversed(ring))
    connector = gdstk.Polygon(ring, layer=layer, datatype=datatype)

    # Clip bridging fingers at the pad's front face (the face that faces the resonator)
    # so the merged net's left edge is a straight vertical line exactly at the pad's
    # front face — not leaking into or past the pad interior.
    (px0, py0), (px1, py1) = launch_bbox
    cx, cy = (px0 + px1) / 2.0, (py0 + py1) / 2.0
    dx, dy = mouth[0] - cx, mouth[1] - cy
    _BIG = 1e5
    if abs(dx) >= abs(dy):
        # vertical facing edge: front face = px1 (dx>=0) or px0 (dx<0)
        front_x = px1 if dx >= 0 else px0
        if dx >= 0:
            keep_half = gdstk.Polygon([(front_x, py0 - _BIG), (front_x, py1 + _BIG),
                                        (front_x + _BIG, py1 + _BIG), (front_x + _BIG, py0 - _BIG)])
        else:
            keep_half = gdstk.Polygon([(front_x - _BIG, py0 - _BIG), (front_x - _BIG, py1 + _BIG),
                                        (front_x, py1 + _BIG), (front_x, py0 - _BIG)])
    else:
        # horizontal facing edge: front face = py1 (dy>=0) or py0 (dy<0)
        front_y = py1 if dy >= 0 else py0
        if dy >= 0:
            keep_half = gdstk.Polygon([(px0 - _BIG, front_y), (px0 - _BIG, front_y + _BIG),
                                        (px1 + _BIG, front_y + _BIG), (px1 + _BIG, front_y)])
        else:
            keep_half = gdstk.Polygon([(px0 - _BIG, front_y - _BIG), (px0 - _BIG, front_y),
                                        (px1 + _BIG, front_y), (px1 + _BIG, front_y - _BIG)])

    # Clip each bridging piece to the resonator-side half only.
    clipped_bridging: list[gdstk.Polygon] = []
    for bp in contact.bridging:
        cb = gdstk.boolean([bp], [keep_half], "and", precision=precision)
        clipped_bridging.extend(cb)

    # Merge connector + clipped bridging + any extra pieces.
    # The connector's launch corners already sit at the pad front face, so the
    # merged net's leftmost edge is the pad front face — a straight vertical line.
    pieces = [connector, *clipped_bridging, *merge_polys]
    merged = gdstk.boolean(pieces, [], "or", precision=precision)
    if merged:
        net = max(merged, key=lambda p: abs(p.area()))
        net = gdstk.Polygon(_poly_points(net), layer=layer, datatype=datatype)
    else:
        net = connector

    min_angle = _min_interior_angle_deg(ring)
    body_overlap = _overlap_area(connector, body_polys, precision=precision)
    return SignalRoute(
        terminal=terminal,
        layer=layer,
        datatype=datatype,
        connector=connector,
        net=net,
        contact=contact,
        pad_corners=(launch_hi, launch_lo),
        arc_len=len(arc),
        min_angle_deg=min_angle,
        body_overlap_um2=body_overlap,
    )


# --------------------------------------------------------------------------- #
# Step 7 — ground filler (notch the MBE plane around the signal at DRC clearance)
# --------------------------------------------------------------------------- #
def build_ground_filler(
    filler_polys: Sequence[gdstk.Polygon],
    clear_specs: Sequence[tuple[Sequence[gdstk.Polygon], float]],
    connection_polys: Sequence[gdstk.Polygon],
    *,
    layer: int,
    datatype: int,
    precision: float = 1e-3,
) -> list[gdstk.Polygon]:
    """
    Ground filler: a carved right-side plane plus the collar-trace connection.

    The filler must not overlap the resonator interior, so it is carved by every
    ``(polys, clearance_um)`` in ``clear_specs`` (the signal route at full DRC
    clearance, the resonator body at a small gap). It then unions
    ``connection_polys`` — the collar-trace tab (entering at the intercepts and
    following the collar boundary) plus any MBE cap over a grounded MTE
    extension — so the filler attaches only at the collar. All resulting pieces
    are returned, re-tagged to ``layer``/``datatype``.
    """
    if not filler_polys:
        return []
    cut: list[gdstk.Polygon] = []
    for polys, clearance in clear_specs:
        valid = [p for p in polys if p is not None]
        if valid and clearance > 0:
            cut.extend(gdstk.offset(valid, clearance, join="round", precision=precision))
        elif valid:
            cut.extend(valid)
    carved = gdstk.boolean(filler_polys, cut, "not", precision=precision) if cut else list(filler_polys)

    pieces = [*carved, *connection_polys]
    merged = gdstk.boolean(pieces, [], "or", precision=precision) if pieces else carved
    return [gdstk.Polygon(_poly_points(p), layer, datatype) for p in merged]


# --------------------------------------------------------------------------- #
# Step 8 — resonator shift (automatic, bounded retries)
# --------------------------------------------------------------------------- #
def _translate(polys: Sequence[gdstk.Polygon], dx: float, dy: float) -> list[gdstk.Polygon]:
    return [
        gdstk.Polygon([(x + dx, y + dy) for x, y in p.points], layer=p.layer, datatype=p.datatype)
        for p in polys
    ]


@dataclass
class ShiftedRoute:
    """Signal route plus the resonator shift used to achieve it."""

    route: SignalRoute
    shift: Point
    attempts: int
    triggered: bool  # whether a shift away from (0,0) was applied


def route_signal_with_shift(
    connect_polys: Sequence[gdstk.Polygon],
    body_polys: Sequence[gdstk.Polygon],
    launch_polys: Sequence[gdstk.Polygon],
    release_holes: Sequence[gdstk.Polygon],
    *,
    terminal: str,
    layer: int,
    datatype: int,
    merge_polys: Sequence[gdstk.Polygon] = (),
    clamp_launch: bool = False,
    min_angle_deg: float = 30.0,
    max_release_overlap_um2: float = 0.0,
    max_tries: int = 3,
    alpha_um: float = 5.0,
    precision: float = 1e-3,
) -> ShiftedRoute | None:
    """
    Build the signal route, shifting the resonator up/down/left/right to remove
    acute angles or release-hole overlap.

    The resonator (body + connect) moves rigidly by a cumulative delta; the
    launch geometry (GSG pad or MBE filler) and ``merge_polys`` stay fixed. Each
    try evaluates the four orthogonal nudges of size ``alpha_um`` and keeps the
    best improvement, for at most ``max_tries`` steps.
    """
    def evaluate(dx: float, dy: float) -> SignalRoute | None:
        conn = _translate(connect_polys, dx, dy)
        body = _translate(body_polys, dx, dy)
        contact = extract_collar_contact(conn, body, signal_pad_polys=launch_polys, precision=precision)
        if contact is None:
            return None
        return build_signal_route(
            contact, launch_polys, body,
            terminal=terminal, layer=layer, datatype=datatype,
            merge_polys=merge_polys, clamp_launch=clamp_launch, precision=precision,
        )

    def release_overlap(route: SignalRoute, dx: float, dy: float) -> float:
        holes = _translate(release_holes, dx, dy)
        return _overlap_area(route.connector, holes, precision=precision) if holes else 0.0

    def score(route: SignalRoute, dx: float, dy: float) -> tuple[float, float]:
        # Higher min_angle better; release overlap is a hard penalty.
        return (route.min_angle_deg, -release_overlap(route, dx, dy))

    best = evaluate(0.0, 0.0)
    if best is None:
        return None
    dx, dy = 0.0, 0.0
    best_score = score(best, dx, dy)
    attempts = 0

    def clean(route: SignalRoute, sx: float, sy: float) -> bool:
        return route.min_angle_deg >= min_angle_deg and release_overlap(route, sx, sy) <= max_release_overlap_um2

    while attempts < max_tries and not clean(best, dx, dy):
        attempts += 1
        step = alpha_um * attempts
        improved = False
        for ndx, ndy in ((step, 0.0), (-step, 0.0), (0.0, step), (0.0, -step)):
            cand = evaluate(dx + ndx, dy + ndy)
            if cand is None:
                continue
            cand_score = score(cand, dx + ndx, dy + ndy)
            if cand_score > best_score:
                best, best_score = cand, cand_score
                best_dx, best_dy = dx + ndx, dy + ndy
                improved = True
        if not improved:
            break
        dx, dy = best_dx, best_dy

    return ShiftedRoute(route=best, shift=(dx, dy), attempts=attempts, triggered=(dx != 0.0 or dy != 0.0))


# --------------------------------------------------------------------------- #
# Batch orchestration (one routed resonator + export)
# --------------------------------------------------------------------------- #
def _route_poly_key(poly: gdstk.Polygon) -> tuple[float, float, float, float, float]:
    bb = poly.bounding_box()
    if bb is None:
        return (0.0, 0.0, 0.0, 0.0, 0.0)
    (x0, y0), (x1, y1) = bb
    return (round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2), round(abs(poly.area()), 1))


@dataclass
class ResonatorRoute:
    """Final routed geometry for one resonator: signal net + ground filler."""

    index: int
    inst_name: str
    terminal: str                       # "MTE" (center_pad) or "MBE" (collar_extend)
    signal_net: gdstk.Polygon | None
    filler_nets: list[gdstk.Polygon]
    strip_keys: set                     # frame MTE/MBE polygons to delete
    signal_intercepts: tuple[Point, Point] | None

    def summary_row(self) -> dict[str, object]:
        return {
            "index": self.index,
            "inst_name": self.inst_name,
            "terminal": self.terminal,
            "signal_drawn": self.signal_net is not None,
            "signal_net_verts": len(self.signal_net.points) if self.signal_net else 0,
            "filler_pieces": len(self.filler_nets),
            "filler_area_um2": round(sum(abs(p.area()) for p in self.filler_nets), 1),
            "wild_removed": len(self.strip_keys),
        }


def build_resonator_route(
    roles: object,
    classification: object,
    layermap: LayerMap,
    *,
    signal_clearance_um: float = 21.0,
    body_clearance_um: float = 3.0,
    precision: float = 1e-3,
) -> ResonatorRoute:
    """
    Route one resonator from its step-5.1 roles + step-5.2 classification.

    * **center_pad** → MTE signal to the center pad; MBE ground filler traces the
      resonator body edge (no interior overlap) and edge-touches the MBE ground.
    * **collar_extend** → MBE signal to the center pad; the grounded MTE extension
      is capped with MBE (clear of the MBE signal body) so the filler connects
      from the top without overlapping the resonator.

    Wild preserved MBE filter extensions and orphan MTE are flagged for deletion.
    """
    mte_pair = layermap.pair("BAW_MTE")
    mbe_pair = layermap.pair("BAW_MBE")
    all_mte = [tp.polygon for tp in roles.preserved.mte]
    all_mbe = [tp.polygon for tp in roles.preserved.mbe]
    body_mte = list(roles.resonator_body_mte)
    body_mbe = list(roles.resonator_body_mbe)
    signal_pad = [tp.polygon for tp in roles.ground_plates.center]
    filler = [tp.polygon for tp in roles.ground_plates.filler]

    center_pad = getattr(classification, "mte_route_target", "") == "center_pad"
    terminal = "MTE" if center_pad else "MBE"
    if center_pad:
        connect, body, s_layer, s_dt = all_mte, body_mte, mte_pair[0], mte_pair[1]
    else:
        connect, body, s_layer, s_dt = all_mbe, body_mbe, mbe_pair[0], mbe_pair[1]

    strip: set = set()
    signal_net: gdstk.Polygon | None = None
    intercepts: tuple[Point, Point] | None = None

    # --- signal route ---
    contact = extract_collar_contact(connect, body, signal_pad_polys=signal_pad, precision=precision)
    if contact is not None and signal_pad:
        route = build_signal_route(
            contact, signal_pad, body, terminal=terminal,
            layer=s_layer, datatype=s_dt, clamp_launch=False, precision=precision,
        )
        signal_net = route.net
        intercepts = (contact.intercept_a, contact.intercept_b)
        strip |= {_route_poly_key(p) for p in contact.bridging}

    # --- ground filler ---
    filler_nets: list[gdstk.Polygon] = []
    if filler:
        # Clip filler height to the outer extent of the GSG top/bottom ground plates
        # so the filler rectangle aligns with the frame's MBE plate height.
        top_bb = polys_bbox([tp.polygon for tp in roles.ground_plates.top])
        bot_bb = polys_bbox([tp.polygon for tp in roles.ground_plates.bottom])
        if top_bb and bot_bb:
            y_hi = top_bb[1][1]
            y_lo = bot_bb[0][1]
            _BIG = 1e5
            height_mask = gdstk.Polygon([(-_BIG, y_lo), (-_BIG, y_hi), (_BIG, y_hi), (_BIG, y_lo)])
            filler_clipped: list[gdstk.Polygon] = []
            for fp in filler:
                filler_clipped.extend(gdstk.boolean([fp], [height_mask], "and", precision=precision))
        else:
            filler_clipped = list(filler)

        sig_route = [signal_net] if signal_net is not None else []
        if center_pad:                      # ground = MBE: trace body edge, edge-touch
            connection: list[gdstk.Polygon] = []
            clear_specs = [(sig_route, signal_clearance_um),
                           ([*body_mte, *body_mbe], 0.0)]
        else:                               # ground = grounded MTE: cap the top
            g_bridging, _ = split_bridging_orphans(all_mte, body_mte, precision=precision)
            connection = [
                gdstk.Polygon(p.points, mbe_pair[0], mbe_pair[1])
                for p in g_bridging
                if _overlap_area(p, body_mbe, precision=precision) < 0.4 * abs(p.area())
            ]
            clear_specs = [(sig_route, signal_clearance_um),
                           ([*body_mbe, *body_mte], body_clearance_um)]
        filler_nets = build_ground_filler(
            filler_clipped, clear_specs, connection,
            layer=mbe_pair[0], datatype=mbe_pair[1], precision=precision,
        )
        strip |= {_route_poly_key(p) for p in filler}

    # --- cleanup: orphan MTE + wild preserved MBE filter extensions ---
    strip |= {_route_poly_key(p) for p in transitive_orphans(all_mte, body_mte, precision=precision)}
    strip |= {_route_poly_key(p) for p in all_mbe}

    return ResonatorRoute(
        index=roles.index,
        inst_name=roles.inst_name,
        terminal=terminal,
        signal_net=signal_net,
        filler_nets=filler_nets,
        strip_keys=strip,
        signal_intercepts=intercepts,
    )


def build_all_routes(
    roles_by_index: "dict[int, object]",
    classifications: "dict[int, object]",
    layermap: LayerMap,
    *,
    indices: Sequence[int] | None = None,
    **kwargs: object,
) -> dict[int, ResonatorRoute]:
    """Route every resonator index present in both maps (or a subset)."""
    out: dict[int, ResonatorRoute] = {}
    keys = indices if indices is not None else sorted(roles_by_index)
    for idx in keys:
        if idx not in roles_by_index or idx not in classifications:
            continue
        out[idx] = build_resonator_route(
            roles_by_index[idx], classifications[idx], layermap, **kwargs
        )
    return out


@dataclass
class RouteNewAssembly:
    """Adapts a routed resonator into an exportable (flattened) assembly."""

    index: int
    inst_name: str
    frame_assembly: object              # step-4 RtegFrameAssembly (duck-typed)
    route: ResonatorRoute
    layermap: LayerMap
    _cell: gdstk.Cell | None = field(default=None, repr=False)

    def _build(self) -> gdstk.Cell:
        if self._cell is not None:
            return self._cell
        mte_pair = self.layermap.pair("BAW_MTE")
        mbe_pair = self.layermap.pair("BAW_MBE")
        flat = self.frame_assembly.flatten()
        cell = gdstk.Cell(f"rteg_{self.index:02d}_{self.inst_name}")
        for poly in flat.polygons:
            if (poly.layer, poly.datatype) in (mte_pair, mbe_pair) and (
                _route_poly_key(poly) in self.route.strip_keys
            ):
                continue
            cell.add(poly)
        if self.route.signal_net is not None:
            cell.add(self.route.signal_net)
        for fp in self.route.filler_nets:
            cell.add(fp)
        self._cell = cell
        return cell

    @property
    def top_cell(self) -> gdstk.Cell:
        return self._build()

    @property
    def library(self) -> gdstk.Library:
        lib = gdstk.Library()
        lib.add(self._build())
        return lib

    def flatten(self) -> gdstk.Cell:
        return self._build()


def export_route_new_gds(
    frame_assemblies: Sequence[object],
    routes: "dict[int, ResonatorRoute]",
    output_dir: object,
    *,
    layermap: LayerMap,
    parent: str | None = None,
    stage: str = "",
    write_lyp: bool = True,
) -> list:
    """Export one complete routed GDS per resonator (frame + signal + filler)."""
    from export_gds import export_gds

    assemblies = [
        RouteNewAssembly(asm.index, asm.inst_name, asm, routes[asm.index], layermap)
        for asm in frame_assemblies
        if asm.index in routes
    ]
    return export_gds(
        assemblies, output_dir, layermap=layermap, parent=parent,
        stage=stage, flatten=True, write_lyp=write_lyp,
    )


def routes_overview_rows(routes: "dict[int, ResonatorRoute]") -> list[dict[str, object]]:
    """Rows for a pandas DataFrame in the notebook."""
    return [routes[i].summary_row() for i in sorted(routes)]


__all__ = [
    "ResonatorRoute",
    "RouteNewAssembly",
    "CollarContact",
    "ShiftedRoute",
    "SignalRoute",
    "build_all_routes",
    "build_ground_filler",
    "build_resonator_route",
    "build_signal_route",
    "export_route_new_gds",
    "extract_all_contacts",
    "extract_collar_contact",
    "route_signal_with_shift",
    "routes_overview_rows",
    "select_signal_contact",
    "split_bridging_orphans",
    "transitive_orphans",
]
