"""Quick check: metal-bbox mouth aim heuristics vs resonator 6 golden coords."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import gdstk

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parents[1] / "tests"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(TESTS))

from kb331_pipeline import load_kb331_pipeline
from prep_resonator_ppd import resonator_metal_polys
from rteg_collect import (
    RtegCollectConfig,
    _expand_bbox,
    _resonator_body_mbe_at_filter,
    _resonator_body_mte_at_filter,
    collect_filter_preserved_metal,
    preserved_mbe_overlap_with_body,
    preserved_mte_overlap_with_body,
)
from rteg_mte_extensions import polys_touch
from rteg_utils import polys_bbox, resonator_world_bbox

GOLDEN_6 = {
    "MTE": ((224, 235), (196, 341)),
    "MBE": ((221, 335), (274, 244)),
}

AIMS = {
    "MTE": {"A": (-33.0, -18.0, 0.0), "B": (-61.0, 0.0, 0.68)},
    "MBE": {"A": (-36.0, 0.0, 0.66), "B": (17.0, 0.0, -0.07)},
}


def nearest_edge(poly: gdstk.Polygon, tx: float, ty: float) -> tuple[float, float]:
    pts = [(float(x), float(y)) for x, y in poly.points]
    best = 999.0
    best_pt = (tx, ty)
    for i in range(len(pts)):
        p0, p1 = pts[i], pts[(i + 1) % len(pts)]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        el2 = dx * dx + dy * dy
        if el2 < 1e-9:
            continue
        t = max(0.0, min(1.0, ((tx - p0[0]) * dx + (ty - p0[1]) * dy) / el2))
        pt = (p0[0] + t * dx, p0[1] + t * dy)
        d = math.hypot(pt[0] - tx, pt[1] - ty)
        if d < best:
            best = d
            best_pt = pt
    return best_pt


def build_cluster(
    flat,
    res,
    identification,
    layermap,
    pair,
    body,
    overlap_fn,
    cfg: RtegCollectConfig,
) -> list[gdstk.Polygon]:
    bb = _expand_bbox(resonator_world_bbox(res), cfg.preserved_overlap_margin_um)

    def overlaps(poly: gdstk.Polygon) -> bool:
        b = poly.bounding_box()
        if b is None:
            return False
        (x0, y0), (x1, y1) = bb
        (ax0, ay0), (ax1, ay1) = b
        return ax0 <= x1 and x0 <= ax1 and ay0 <= y1 and y0 <= ay1

    preserved = collect_filter_preserved_metal(res, identification, layermap, cfg)
    mte_pair = layermap.pair("BAW_MTE")
    seeds = [
        tp.polygon
        for tp in (preserved.mte if pair == mte_pair else preserved.mbe)
    ]
    all_polys = [
        poly
        for poly in flat.polygons
        if (poly.layer, poly.datatype) == pair and overlaps(poly)
    ]
    cluster = list(seeds)
    changed = True
    while changed:
        changed = False
        for poly in all_polys:
            if poly in cluster:
                continue
            if any(polys_touch(poly, s) for s in cluster):
                cluster.append(poly)
                changed = True
            elif overlap_fn(poly, body) > 0.01:
                cluster.append(poly)
                changed = True
    return cluster


def main() -> None:
    pipeline = load_kb331_pipeline()
    cfg = RtegCollectConfig()
    flat = gdstk.read_gds(str(SRC.parent / "input_files" / "KB331_N_01.gds")).top_level()[
        0
    ].flatten()
    mte_pair = pipeline["layermap"].pair("BAW_MTE")
    mbe_pair = pipeline["layermap"].pair("BAW_MBE")
    res = pipeline["res_list"][6]
    mbb = polys_bbox(resonator_metal_polys(res, 0.0, 0.0))
    mx0, my0 = mbb[0]
    _, my1 = mbb[1]
    h = my1 - my0

    for label, pair, body_fn, overlap_fn in [
        (
            "MTE",
            mte_pair,
            lambda: _resonator_body_mte_at_filter(res, pipeline["layermap"], cfg),
            preserved_mte_overlap_with_body,
        ),
        (
            "MBE",
            mbe_pair,
            lambda: _resonator_body_mbe_at_filter(res, pipeline["layermap"], cfg),
            preserved_mbe_overlap_with_body,
        ),
    ]:
        body = body_fn()
        cluster = build_cluster(
            flat,
            res,
            pipeline["identification"],
            pipeline["layermap"],
            pair,
            body,
            overlap_fn,
            cfg,
        )
        print(f"\n{label} cluster={len(cluster)}")
        for corner, g in zip(("A", "B"), GOLDEN_6[label]):
            ax, ay_fixed, ay_frac = AIMS[label][corner]
            aim = (mx0 + ax, my0 + ay_fixed + ay_frac * h)
            best = None
            best_d = 999.0
            for poly in cluster:
                pt = nearest_edge(poly, aim[0], aim[1])
                d = math.hypot(pt[0] - aim[0], pt[1] - aim[1])
                if d < best_d:
                    best_d = d
                    best = pt
            assert best is not None
            dg = math.hypot(best[0] - g[0], best[1] - g[1])
            print(
                f"  {corner} aim={tuple(round(x, 1) for x in aim)} "
                f"got={tuple(round(x, 2) for x in best)} d_golden={dg:.2f}"
            )


if __name__ == "__main__":
    main()
