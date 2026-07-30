# download_all.py -- 全量下载 Materials Project 所有材料的完整结构（JSON）
# 用法:
#   小批量验证: DL_LIMIT=10 python3 download_all.py
#   全量下载:   python3 download_all.py
import typing
import typing_extensions

for _name in ("NotRequired", "Required"):
    if not hasattr(typing, _name) and hasattr(typing_extensions, _name):
        setattr(typing, _name, getattr(typing_extensions, _name))

import json
import os
import itertools
from pathlib import Path

import pandas as pd
from monty.json import jsanitize
from mp_api.client import MPRester


def _resolve_api_key() -> str:
    key = os.environ.get("MP_API_KEY", "").strip()
    if key:
        return key
    dotenv = Path(".env")
    if dotenv.is_file():
        for raw in dotenv.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line or line.startswith("#"):
                continue
            k, v = line.split("=", 1)
            if k.strip() == "MP_API_KEY":
                return v.strip().strip('"').strip("'")
    return "fFtrdShVJH4jwWHiId8v4cyGzV2oYnoG"


API_KEY = _resolve_api_key()
OUTDIR = Path("structures/all")
OUTDIR.mkdir(parents=True, exist_ok=True)
INDEX_CSV = OUTDIR / "index.csv"

LIMIT = int(os.environ.get("DL_LIMIT", "0"))   # 0 = 全量
SKIP_EXISTING = True

fields = [
    "material_id", "formula_pretty",
    "nsites", "nelements", "symmetry",
    "structure",
]


def _sym_attr(sym, name):
    if sym is None:
        return None
    if isinstance(sym, dict):
        return sym.get(name)
    return getattr(sym, name, None)


rows = []
ok = skipped = errors = 0

print(f"LIMIT={LIMIT} (0=全量)；输出目录: {OUTDIR.resolve()}", flush=True)

with MPRester(API_KEY) as mpr:
    try:
        total_hits = mpr.materials.summary.count()
    except Exception as e:
        print(f"count() 失败: {type(e).__name__}: {e}", flush=True)
        total_hits = None

    docs = mpr.materials.summary.search(fields=fields)
    targets = itertools.islice(docs, LIMIT) if (LIMIT and LIMIT > 0) else docs
    total = LIMIT if (LIMIT and LIMIT > 0) else (total_hits or 0)

    print(f"命中材料数: {total_hits}；本次处理: {total}", flush=True)

    for i, d in enumerate(targets, start=1):
        mid = str(d.material_id)
        target = OUTDIR / f"{mid}.json"
        row = {
            "material_id": mid,
            "formula_pretty": d.formula_pretty,
            "nsites": d.nsites,
            "nelements": d.nelements,
            "crystal_system": _sym_attr(d.symmetry, "crystal_system"),
            "spacegroup_symbol": _sym_attr(d.symmetry, "symbol"),
            "spacegroup_number": _sym_attr(d.symmetry, "number"),
            "json_path": str(target),
            "status": "",
            "error": "",
        }

        if SKIP_EXISTING and target.exists():
            row["status"] = "skipped"
            skipped += 1
        else:
            try:
                data = jsanitize(d.structure.as_dict(), strict=True)
                with open(target, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                row["status"] = "ok"
                ok += 1
            except Exception as e:
                row["status"] = "error"
                row["error"] = f"{type(e).__name__}: {e}"
                errors += 1

        rows.append(row)

        if i % 200 == 0 or (total and i == total):
            print(f"[{i}/{total}] ok={ok} skip={skipped} err={errors}", flush=True)

index = pd.DataFrame(rows).sort_values("material_id").reset_index(drop=True)
index.to_csv(INDEX_CSV, index=False)

print(f"DONE ok={ok} skip={skipped} err={errors} total={len(index)}", flush=True)
print(f"索引: {INDEX_CSV}", flush=True)
