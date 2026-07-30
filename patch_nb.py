# patch_nb.py  --  把 mp_download.ipynb 改为：全量下载 + 仅完整结构 JSON
# 用法: python3 patch_nb.py
import json
from pathlib import Path

NB_PATH = Path(__file__).resolve().parent / "mp_download.ipynb"

CELL0 = r'''# 从 Materials Project 全量下载材料完整结构（JSON）

**目标**：不附加任何筛选条件，全量下载 Materials Project 中所有材料的**完整晶体结构**，以 JSON 文件形式保存。

- 不筛选 `elements` / `band_gap` 等任何条件（全量）
- 不再产出 CIF，改为每个材料输出一个 `{material_id}.json`，内容为 pymatgen `Structure.as_dict()` 的完整序列化结果--含晶格、位点、site properties、磁矩等 CIF 无法表达的字段，可用 `Structure.from_dict()` / `Structure.from_file()` 直接读回

**产出**（位于 `structures/all/`）：

| 文件 | 内容 |
|------|------|
| `*.json` | 各材料的完整结构（晶格、位点、site properties 等） |
| `index.csv` | 索引 + 下载状态（material_id、formula、对称性、json 路径、status、error） |

> 依赖：`pip install mp-api pymatgen pandas monty`
>
> ⚠️ 全量不筛选会命中 MP 全库（约 15 万条），耗时较长、占用磁盘较大。可先把 `LIMIT` 设为一个较小值验证流程，再改回 `0` 跑全量。

## 1. 查询 Materials Project

用 `mpr.materials.summary.search(fields=...)` **不带任何筛选参数**做全量拉取，只取结构相关字段：

- `material_id`、`formula_pretty` - 标识
- `nsites`、`nelements`、`symmetry` - 索引用
- `structure` - 用于写 JSON

> 惰性分页迭代，不一次性 `list()` 全库，避免内存爆炸。

## 2. 写出完整结构 JSON 并建索引

逐条把 `structure.as_dict()` 经 `monty.json.jsanitize` 转成 JSON 原生类型后写出；同时累积一张 `index.csv`（含下载状态）。
'''

CELL1 = r'''# ---- Python 3.10 兼容性 shim（必须在导入 mp_api 之前）----
# emmet-core 新版在 emmet/core/tasks.py 里直接 `from typing import NotRequired`，
# 但 NotRequired/Required 是 Python 3.11+ 才进标准库 typing 的。
# 这里先从 typing_extensions 把它们补丁进 typing，使 Python 3.10 也能正常导入。
import typing
import typing_extensions

for _name in ("NotRequired", "Required"):
    if not hasattr(typing, _name) and hasattr(typing_extensions, _name):
        setattr(typing, _name, getattr(typing_extensions, _name))

import json
import os
from pathlib import Path

import pandas as pd
from monty.json import jsanitize
from mp_api.client import MPRester


# -------- 配置 --------
# API key 解析顺序: 环境变量 MP_API_KEY -> ./.env -> demo.py 默认 key
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
    return "fFtrdShVJH4jwWHiId8v4cyGzV2oYnoG"  # 回退到 demo.py 默认 key


API_KEY = _resolve_api_key()

# 输出
OUTDIR = Path("structures/all")
OUTDIR.mkdir(parents=True, exist_ok=True)
INDEX_CSV = OUTDIR / "index.csv"

# 下载选项
LIMIT = 0          # >0 时只处理前 N 条（测试用）；0 = 全量
SKIP_EXISTING = True  # 已存在的 JSON 跳过

print(f"Python {'.'.join(map(str, __import__('sys').version_info[:3]))}  "
      f"NotRequired 可用: {hasattr(typing, 'NotRequired')}")
print(f"输出目录: {OUTDIR.resolve()}")
print(f"模式: 全量下载（不筛选），产出完整结构 JSON；LIMIT={LIMIT}（0=全部）")
'''

CELL2 = r'''import itertools

# 只拉结构相关字段：标识 + 结构 + 对称性（用于索引）
fields = [
    "material_id", "formula_pretty",
    "nsites", "nelements", "symmetry",
    "structure",  # 用于写 JSON
]


def _sym_attr(sym, name):
    """兼容 symmetry 为 dict 或 SymmetryData 对象两种情况。"""
    if sym is None:
        return None
    if isinstance(sym, dict):
        return sym.get(name)
    return getattr(sym, name, None)


# ---- 进度条 ----
try:
    from tqdm.auto import tqdm
    _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False
    print("未安装 tqdm（pip install tqdm），退回到每 200 条打印一次。")


rows = []
ok = skipped = errors = 0

with MPRester(API_KEY) as mpr:
    # 不附加任何筛选条件 -> 全量下载
    try:
        total_hits = mpr.materials.summary.count()
    except Exception:
        total_hits = None

    # 惰性分页迭代器，不一次性 list 全库，避免内存爆炸
    docs = mpr.materials.summary.search(fields=fields)
    targets = itertools.islice(docs, LIMIT) if (LIMIT and LIMIT > 0) else docs
    total = LIMIT if (LIMIT and LIMIT > 0) else (total_hits or 0)

    if total_hits is not None:
        print(f"命中材料数: {total_hits}")
    if LIMIT and 0 < LIMIT < (total_hits or LIMIT):
        print(f"按 LIMIT={LIMIT} 截取，本次处理: {total}")

    iterator = tqdm(targets, total=total or None, desc="写出 JSON", unit="json") if _HAS_TQDM else targets

    for i, d in enumerate(iterator, start=1):
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
                # structure.as_dict() 是 MSONable 标准格式，可用 Structure.from_dict 读回；
                # jsanitize 把 numpy 等类型转成 JSON 原生类型，确保 json.dump 不报错。
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

        if _HAS_TQDM:
            iterator.set_postfix(ok=ok, skip=skipped, err=errors)
        elif i % 200 == 0 or (total and i == total):
            print(f"[{i}/{total}] ok={ok}  skipped={skipped}  errors={errors}")

index = pd.DataFrame(rows).sort_values("material_id").reset_index(drop=True)
index.to_csv(INDEX_CSV, index=False)

print("\n===== 汇总 =====")
print(f"命中: {total_hits} 条；本次处理: {len(index)} 条")
print(f"JSON 目录: {OUTDIR.resolve()}")
print(f"  写出 ok={ok}  跳过 skipped={skipped}  失败 errors={errors}")
print(f"索引/报告: {INDEX_CSV.name}")
print("\n状态分布:")
print(index["status"].value_counts())
'''

with open(NB_PATH, encoding="utf-8") as f:
    nb = json.load(f)


def to_source(s):
    return s.splitlines(keepends=True)


for i, src in {0: CELL0, 1: CELL1, 2: CELL2}.items():
    nb["cells"][i]["source"] = to_source(src)
    if nb["cells"][i]["cell_type"] == "code":
        nb["cells"][i]["outputs"] = []
        nb["cells"][i]["execution_count"] = None

with open(NB_PATH, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
    f.write("\n")

with open(NB_PATH, encoding="utf-8") as f:
    nb2 = json.load(f)
print("OK, cells:", len(nb2["cells"]))
for i in range(3):
    src = "".join(nb2["cells"][i]["source"])
    print(f"--- Cell {i} [{nb2['cells'][i]['cell_type']}] {len(src)} chars ---")
    print(src[:120])
