# download_props.py -- 下载 Na bandgap≥1 子集各材料的全部可用性质（JSON）
#
# 覆盖的端点（已验证可在当前环境拉取）：
#   summary(去嵌套) thermo(去entries) elasticity dielectric piezoelectric
#   magnetism oxidation_states chemenv provenance bonds(去structure_graph)
#   absorption surface_properties grain_boundaries robocrys(get_data_by_id)
#
# 被阻塞的重型谱端点（本地 emmet/pymatgen 与服务端 schema 版本不匹配）：
#   electronic_structure(DOS/能带) xas phonon eos
#   —— 这些端点按 task_id 索引、material_id 不可靠，需升级 mp_api/emmet/pymatgen 后再取。
#
# 用法:
#   小批量验证: DL_LIMIT=3 python download_props.py
#   指定端点:   ENDPOINTS=summary,thermo python download_props.py
#   全量下载:   python download_props.py
import typing
import typing_extensions

for _name in ("NotRequired", "Required"):
    if not hasattr(typing, _name) and hasattr(typing_extensions, _name):
        setattr(typing, _name, getattr(typing_extensions, _name))

import csv
import json
import os
import time
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
CIF_DIR = Path("cif/na_bandgap_ge1")
OUTDIR = Path("props")
OUTDIR.mkdir(parents=True, exist_ok=True)

LIMIT = int(os.environ.get("DL_LIMIT", "0"))        # 0 = 全量
CHUNK = int(os.environ.get("DL_CHUNK", "100"))      # batch 端点每批 material_id 数
SLEEP = float(os.environ.get("DL_SLEEP", "0.0"))    # 每批之间休眠秒数
ONLY_ENDPOINTS = (
    {s.strip() for s in os.environ.get("ENDPOINTS", "").split(",") if s.strip()}
    if os.environ.get("ENDPOINTS") else None
)

# (端点名, 模式, 需排除的字段集合)
# 模式: "batch" = search(material_ids=chunk, fields=...) ; "by_id" = get_data_by_id 逐个
ENDPOINTS = [
    ("summary", "batch", {"bandstructure", "dos", "xas", "grain_boundaries"}),
    ("thermo", "batch", {"entries", "entry_types", "decomposes_to",
                         "decomposition_enthalpy_decomposes_to"}),
    ("elasticity", "batch", None),
    ("dielectric", "batch", None),
    ("piezoelectric", "batch", None),
    ("magnetism", "batch", None),
    ("oxidation_states", "batch", None),
    ("chemenv", "batch", None),
    ("provenance", "batch", None),
    ("bonds", "batch", {"structure_graph"}),
    ("absorption", "batch", None),
    ("surface_properties", "batch", None),
    ("grain_boundaries", "batch", None),
    ("robocrys", "by_id", None),
]


def read_material_ids() -> list[str]:
    cifs = sorted(CIF_DIR.glob("mp-*.cif"))
    return [p.stem for p in cifs]


def _chunked(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _status_path(ep: str) -> Path:
    return OUTDIR / ep / "_status.json"


def load_status(ep: str) -> dict:
    p = _status_path(ep)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_status(ep: str, status: dict) -> None:
    p = _status_path(ep)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(p)


def _serialize(doc) -> object:
    return jsanitize(doc.model_dump(mode="json"), strict=True)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def fetch_batch(mpr, ep: str, exclude, mids: list[str]) -> dict:
    rester = getattr(mpr.materials, ep)
    fields = [f for f in rester.available_fields if f not in exclude] if exclude else list(rester.available_fields)
    status = load_status(ep)
    outdir = OUTDIR / ep
    todo = [m for m in mids if m not in status]
    n_todo = len(todo)
    print(f"[{ep}] batch  待取 {n_todo}/{len(mids)}  fields={len(fields)}", flush=True)

    for i, chunk in enumerate(_chunked(todo, CHUNK), start=1):
        if SLEEP and i > 1:
            time.sleep(SLEEP)
        try:
            docs = rester.search(material_ids=chunk, fields=fields)
        except Exception as e:
            print(f"[{ep}] chunk {i} search 失败: {type(e).__name__}: {str(e)[:120]}", flush=True)
            for m in chunk:
                status[m] = "error"
            save_status(ep, status)
            continue

        by_mid: dict[str, list] = {}
        for d in docs:
            mid = str(d.material_id)
            try:
                obj = _serialize(d)
            except Exception as e:
                print(f"[{ep}] 序列化 {mid} 失败: {type(e).__name__}: {str(e)[:80]}", flush=True)
                status[mid] = "error"
                continue
            by_mid.setdefault(mid, []).append(obj)

        for m in chunk:
            if status.get(m) == "error" and m in by_mid:
                pass  # 上一轮序列化失败，本轮跳过写文件
            if m in by_mid:
                payload = by_mid[m][0] if len(by_mid[m]) == 1 else by_mid[m]
                _write_json(outdir / f"{m}.json", payload)
                status[m] = "ok"
            else:
                status[m] = "empty"
        save_status(ep, status)

        done = min(i * CHUNK, n_todo)
        ok = sum(1 for v in status.values() if v == "ok")
        emp = sum(1 for v in status.values() if v == "empty")
        err = sum(1 for v in status.values() if v == "error")
        print(f"[{ep}] [{done}/{n_todo}] ok={ok} empty={emp} err={err}", flush=True)
    return status


def fetch_by_id(mpr, ep: str, mids: list[str]) -> dict:
    rester = getattr(mpr.materials, ep)
    status = load_status(ep)
    outdir = OUTDIR / ep
    todo = [m for m in mids if m not in status]
    n_todo = len(todo)
    print(f"[{ep}] by_id  待取 {n_todo}/{len(mids)}", flush=True)

    for i, mid in enumerate(todo, start=1):
        try:
            doc = rester.get_data_by_id(mid)
        except Exception as e:
            print(f"[{ep}] {mid} 获取失败: {type(e).__name__}: {str(e)[:80]}", flush=True)
            status[mid] = "error"
            save_status(ep, status)
            continue
        if doc is None:
            status[mid] = "empty"
        else:
            try:
                payload = _serialize(doc)
                _write_json(outdir / f"{mid}.json", payload)
                status[mid] = "ok"
            except Exception as e:
                print(f"[{ep}] {mid} 序列化失败: {type(e).__name__}: {str(e)[:80]}", flush=True)
                status[mid] = "error"
        if i % 200 == 0 or i == n_todo:
            save_status(ep, status)
            ok = sum(1 for v in status.values() if v == "ok")
            emp = sum(1 for v in status.values() if v == "empty")
            err = sum(1 for v in status.values() if v == "error")
            print(f"[{ep}] [{i}/{n_todo}] ok={ok} empty={emp} err={err}", flush=True)
    return status


def build_index(mids: list[str], ep_names: list[str]) -> None:
    rows = []
    for mid in mids:
        row = {"material_id": mid}
        for ep in ep_names:
            st = load_status(ep).get(mid, "")
            row[ep] = st
        rows.append(row)
    df = pd.DataFrame(rows)
    # 附 formula_pretty（若 summary 已写入则从 JSON 读）
    formulas = {}
    for mid in mids:
        f = OUTDIR / "summary" / f"{mid}.json"
        if f.is_file():
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                formulas[mid] = d.get("formula_pretty", "")
            except Exception:
                pass
    if formulas:
        df.insert(1, "formula_pretty", df["material_id"].map(formulas).fillna(""))
    df.to_csv(OUTDIR / "index.csv", index=False)
    print(f"索引已写入: {OUTDIR/'index.csv'}  ({len(df)} 行)", flush=True)
    # 各端点统计
    print("--- 各端点状态统计 ---", flush=True)
    for ep in ep_names:
        st = load_status(ep)
        from collections import Counter
        c = Counter(st.values())
        print(f"  {ep:22s} ok={c.get('ok',0)} empty={c.get('empty',0)} err={c.get('error',0)}", flush=True)


def main() -> int:
    mids = read_material_ids()
    if LIMIT and LIMIT > 0:
        mids = mids[:LIMIT]
    if not mids:
        print(f"未在 {CIF_DIR} 找到 mp-*.cif 文件", flush=True)
        return 2

    eps = [(n, m, e) for (n, m, e) in ENDPOINTS if not ONLY_ENDPOINTS or n in ONLY_ENDPOINTS]
    ep_names = [n for n, _, _ in eps]
    print(f"材料数: {len(mids)}  端点: {ep_names}", flush=True)
    print(f"输出目录: {OUTDIR.resolve()}", flush=True)

    with MPRester(API_KEY) as mpr:
        for ep, mode, exclude in eps:
            t0 = time.time()
            if mode == "batch":
                fetch_batch(mpr, ep, exclude, mids)
            else:
                fetch_by_id(mpr, ep, mids)
            print(f"[{ep}] 耗时 {time.time()-t0:.0f}s", flush=True)

    build_index(mids, ep_names)
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
