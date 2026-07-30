#!/usr/bin/env python3
"""Compute Na polyhedron distortion for every CIF in a directory.

This is a standalone script. It does not import compute_descriptors_from_cif.py
or any project-local module.

Definition used here:

    per Na site distortion = pstdev(Na-X distances) / mean(Na-X distances)
    file-level na_poly_distortion = mean(per Na site distortion)

For each Na site, X means first-shell anion neighbors from:

    O, S, Se, F, Cl, Br, I, N, H

Usage:

    python dataset/compute_na_poly_distortion_batch.py dataset/cif
    python dataset/compute_na_poly_distortion_batch.py dataset/cif --recursive
    python dataset/compute_na_poly_distortion_batch.py dataset/cif --output-csv out.csv

Outputs:

    na_poly_distortion_by_cif.csv

The output is one row per CIF. Failed CIFs are kept in the CSV with status=error
so the batch result is auditable.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

import numpy as np
from pymatgen.io.cif import CifParser
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

try:
    from scipy.spatial import ConvexHull, QhullError
except Exception:  # pragma: no cover
    ConvexHull = None
    QhullError = Exception


MOBILE = "Na"
ANION_ELEMENTS = {"O", "S", "Se", "F", "Cl", "Br", "I", "N", "H"}
ROUND_TO_IDEAL_RE = re.compile(r"rounded to ideal values", re.I)

FIELDNAMES = [
    "status",
    "cif_file",
    "cif_path",
    "pymatgen_reduced_formula",
    "spacegroup",
    "na_poly_distortion",
    "na_site_count",
    "anion_types",
    "na_main_cn",
    "na_x_avg_bond_A",
    "na_x_min_bond_A",
    "na_x_max_bond_A",
    "na_poly_avg_volume_A3",
    "na_poly_volume_range_A3",
    "issue_count",
    "issues",
]


def resolve_path(path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else (Path.cwd() / p)


def find_cifs(cif_dir: Path, pattern: str, recursive: bool) -> list[Path]:
    finder = cif_dir.rglob if recursive else cif_dir.glob
    return sorted(p for p in finder(pattern) if p.is_file())


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return round(float(value), digits)


def fmt_range(values: list[float], digits: int = 3) -> str | None:
    clean_values = [float(v) for v in values if v is not None and not math.isnan(float(v))]
    if not clean_values:
        return None
    return f"{min(clean_values):.{digits}f}-{max(clean_values):.{digits}f}"


def site_species_dict(site) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for el, occ in site.species.items():
        out[str(getattr(el, "symbol", str(el)))] += float(occ)
    return dict(out)


def site_occ(site, symbol: str) -> float:
    return site_species_dict(site).get(symbol, 0.0)


def major_symbol(site) -> str:
    species = site_species_dict(site)
    if not species:
        return str(site.specie.symbol)
    return sorted(species.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def anion_cutoff(anion_symbols: set[str]) -> float:
    cutoffs = {
        "O": 3.20,
        "F": 3.20,
        "N": 3.35,
        "S": 3.85,
        "Cl": 3.85,
        "Se": 4.05,
        "Br": 4.05,
        "I": 4.35,
        "H": 3.20,
    }
    return max((cutoffs.get(sym, 4.0) for sym in anion_symbols), default=4.0)


def unpack_neighbor(item: Any, center_coords: np.ndarray) -> tuple[Any, float, int | None, np.ndarray]:
    if isinstance(item, tuple):
        site = item[0]
        dist = float(item[1])
        idx = int(item[2]) if len(item) >= 3 and item[2] is not None else None
        return site, dist, idx, np.array(site.coords, dtype=float)
    site = item
    dist = getattr(item, "nn_distance", None)
    if dist is None:
        dist = float(np.linalg.norm(np.array(site.coords, dtype=float) - center_coords))
    idx = getattr(item, "index", None)
    return site, float(dist), idx, np.array(site.coords, dtype=float)


def shell_neighbors(structure, center_index: int, anion_symbols: set[str]) -> list[dict[str, Any]]:
    """Return first-shell anion neighbors around one Na site.

    The first shell keeps all anions within nearest_anion_distance + 0.70 A.
    If that would leave only 0-3 neighbors while more anions are available,
    the nearest 4 are kept so common Na coordination polyhedra are not
    undercounted by a small bond-length split.
    """
    center = structure[center_index]
    raw = structure.get_sites_in_sphere(
        center.coords, anion_cutoff(anion_symbols), include_index=True, include_image=True
    )
    neighbors = []
    center_coords = np.array(center.coords, dtype=float)
    for item in raw:
        site, dist, idx, coords = unpack_neighbor(item, center_coords)
        if idx == center_index and dist < 1e-6:
            continue
        sym = major_symbol(site)
        if sym in anion_symbols:
            neighbors.append({"symbol": sym, "distance": dist, "coords": coords, "index": idx})
    neighbors.sort(key=lambda x: x["distance"])
    if not neighbors:
        return []
    first = neighbors[0]["distance"]
    kept = [n for n in neighbors if n["distance"] <= first + 0.70]
    if len(kept) <= 3 and len(neighbors) > len(kept):
        kept = neighbors[: min(4, len(neighbors))]
    return kept


def mode_int(values: list[int]) -> int | None:
    if not values:
        return None
    return sorted(Counter(values).items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def convex_volume(coords: list[np.ndarray]) -> float | None:
    if len(coords) < 4 or ConvexHull is None:
        return None
    try:
        return float(ConvexHull(np.array(coords, dtype=float)).volume)
    except (QhullError, ValueError):
        return None


def spacegroup_from_cif_text(cif_path: Path) -> str | None:
    try:
        text = cif_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    sym = num = None
    m = re.search(r"_symmetry_space_group_name_H-M\s+['\"]?([^'\"\n]+?)['\"]?\s*\n", text)
    if m:
        sym = m.group(1).strip()
    if not sym:
        m = re.search(r"_space_group_name_H-M_alt\s+['\"]?([^'\"\n]+?)['\"]?\s*\n", text)
        if m:
            sym = m.group(1).strip()
    m = re.search(r"_symmetry_Int_Tables_number\s+(\d+)", text)
    if m:
        num = m.group(1)
    if not num:
        m = re.search(r"_space_group_IT_number\s+(\d+)", text)
        if m:
            num = m.group(1)
    if sym and num:
        return f"{sym} ({num})"
    return sym or (f"#{num}" if num else None)


def get_spacegroup(structure, cif_path: Path, issues: list[str]) -> str | None:
    try:
        sga = SpacegroupAnalyzer(structure, symprec=0.01)
        return f"{sga.get_space_group_symbol()} ({sga.get_space_group_number()})"
    except Exception:
        try:
            sga = SpacegroupAnalyzer(structure, symprec=0.1)
            return f"{sga.get_space_group_symbol()} ({sga.get_space_group_number()})"
        except Exception as exc:
            sg = spacegroup_from_cif_text(cif_path)
            if sg is None:
                issues.append(f"space group failed: {exc}")
                return None
            return f"{sg} [from CIF header]"


def compute_na_poly_distortion(cif_path: Path) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    parser = CifParser(str(cif_path), occupancy_tolerance=10)
    structure = parser.parse_structures(primitive=False)[0]
    issues.extend(str(w) for w in parser.warnings if not ROUND_TO_IDEAL_RE.search(str(w)))

    species_symbols = {str(getattr(el, "symbol", str(el))) for el in structure.composition.elements}
    anions = species_symbols & ANION_ELEMENTS
    na_sites = [(i, site, site_occ(site, MOBILE)) for i, site in enumerate(structure) if site_occ(site, MOBILE) > 1e-6]

    all_na_x_distances: list[float] = []
    cn_values: list[int] = []
    poly_volumes: list[float] = []
    distortions: list[float] = []

    for idx, _site, _occ in na_sites:
        shell = shell_neighbors(structure, idx, anions)
        distances = [n["distance"] for n in shell]
        cn = len(shell)
        if not cn:
            issues.append(f"Na site {idx} has no first-shell anion neighbors")
            continue

        cn_values.append(cn)
        all_na_x_distances.extend(distances)

        vol = convex_volume([n["coords"] for n in shell])
        if vol is not None:
            poly_volumes.append(vol)

        if len(distances) > 1:
            distortions.append(pstdev(distances) / mean(distances))

    if not na_sites:
        issues.append("no Na sites found")
    if not all_na_x_distances:
        issues.append("no Na-X bonds measured")

    return {
        "pymatgen_reduced_formula": structure.composition.reduced_formula,
        "spacegroup": get_spacegroup(structure, cif_path, issues),
        "na_poly_distortion_mean": round_or_none(mean(distortions) if distortions else None, 5),
        "na_site_count": len(na_sites),
        "anion_types": "/".join(sorted(anions)) if anions else None,
        "na_main_cn": mode_int(cn_values),
        "na_x_avg_bond_A": round_or_none(mean(all_na_x_distances) if all_na_x_distances else None, 4),
        "na_x_min_bond_A": round_or_none(min(all_na_x_distances) if all_na_x_distances else None, 4),
        "na_x_max_bond_A": round_or_none(max(all_na_x_distances) if all_na_x_distances else None, 4),
        "na_poly_avg_volume_A3": round_or_none(mean(poly_volumes) if poly_volumes else None, 4),
        "na_poly_volume_range_A3": fmt_range(poly_volumes),
    }, issues


def row_from_descriptors(cif_path: Path, desc: dict[str, Any], issues: list[str]) -> dict[str, Any]:
    return {
        "status": "ok" if not issues else "ok_with_issues",
        "cif_file": cif_path.name,
        "cif_path": str(cif_path),
        "pymatgen_reduced_formula": desc.get("pymatgen_reduced_formula"),
        "spacegroup": desc.get("spacegroup"),
        "na_poly_distortion": desc.get("na_poly_distortion_mean"),
        "na_site_count": desc.get("na_site_count"),
        "anion_types": desc.get("anion_types"),
        "na_main_cn": desc.get("na_main_cn"),
        "na_x_avg_bond_A": desc.get("na_x_avg_bond_A"),
        "na_x_min_bond_A": desc.get("na_x_min_bond_A"),
        "na_x_max_bond_A": desc.get("na_x_max_bond_A"),
        "na_poly_avg_volume_A3": desc.get("na_poly_avg_volume_A3"),
        "na_poly_volume_range_A3": desc.get("na_poly_volume_range_A3"),
        "issue_count": len(issues),
        "issues": "; ".join(issues),
    }


def error_row(cif_path: Path, exc: Exception) -> dict[str, Any]:
    return {
        "status": "error",
        "cif_file": cif_path.name,
        "cif_path": str(cif_path),
        "pymatgen_reduced_formula": None,
        "spacegroup": None,
        "na_poly_distortion": None,
        "na_site_count": None,
        "anion_types": None,
        "na_main_cn": None,
        "na_x_avg_bond_A": None,
        "na_x_min_bond_A": None,
        "na_x_max_bond_A": None,
        "na_poly_avg_volume_A3": None,
        "na_poly_volume_range_A3": None,
        "issue_count": 1,
        "issues": f"parse/compute failed: {exc}",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute Na polyhedron distortion for all CIF files in a directory."
    )
    parser.add_argument("cif_dir", help="Directory containing CIF files")
    parser.add_argument(
        "--output-csv",
        default="na_poly_distortion_by_cif.csv",
        help="Output CSV path (default: %(default)s)",
    )
    parser.add_argument("--pattern", default="*.cif", help="CIF glob pattern (default: %(default)s)")
    parser.add_argument("--recursive", action="store_true", help="Search CIF files recursively")
    args = parser.parse_args()

    cif_dir = resolve_path(args.cif_dir)
    output_csv = resolve_path(args.output_csv)

    if not cif_dir.exists() or not cif_dir.is_dir():
        raise SystemExit(f"CIF directory not found: {cif_dir}")

    cif_paths = find_cifs(cif_dir, args.pattern, args.recursive)
    if not cif_paths:
        raise SystemExit(f"No CIF files found in {cif_dir} with pattern {args.pattern!r}")

    rows: list[dict[str, Any]] = []
    for cif_path in cif_paths:
        try:
            desc, issues = compute_na_poly_distortion(cif_path)
            rows.append(row_from_descriptors(cif_path, desc, issues))
        except Exception as exc:
            rows.append(error_row(cif_path, exc))

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    ok_count = sum(1 for row in rows if row["status"] != "error")
    error_count = sum(1 for row in rows if row["status"] == "error")
    print(f"processed CIFs: {len(rows)}")
    print(f"ok: {ok_count}")
    print(f"errors: {error_count}")
    print(f"wrote: {output_csv}")


if __name__ == "__main__":
    main()

