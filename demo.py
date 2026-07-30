#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path


def _require_mp_api_and_pymatgen():
    try:
        from mp_api.client import MPRester  # type: ignore
        from pymatgen.io.cif import CifWriter  # type: ignore
        from pymatgen.symmetry.analyzer import SpacegroupAnalyzer  # type: ignore

        return MPRester, CifWriter, SpacegroupAnalyzer
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "缺少依赖：需要安装`mp-api`与`pymatgen`。\n"
            "示例：`pip install mp-api pymatgen`"
        ) from exc


def _load_api_key_from_dotenv(dotenv_path: Path) -> str:
    if not dotenv_path.is_file():
        return ""

    try:
        text = dotenv_path.read_text(encoding="utf-8")
    except OSError:
        return ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "MP_API_KEY":
            continue
        value = value.strip().strip('"').strip("'")
        return value

    return ""


def _read_material_ids(csv_path: Path, column: str) -> list[str]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV没有表头。")
        if column not in reader.fieldnames:
            raise ValueError(f"CSV中找不到列：{column}；实际列：{reader.fieldnames}")

        ids: list[str] = []
        for row in reader:
            mid = (row.get(column) or "").strip()
            if mid:
                ids.append(mid)

    unique = sorted(set(ids))
    return unique


def _chunked(items: list[str], chunk_size: int) -> list[list[str]]:
    if chunk_size <= 0:
        raise ValueError("chunk_size必须为正整数。")
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


@dataclass(frozen=True)
class DownloadResult:
    material_id: str
    path: str
    status: str
    error: str


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "从Materials Project按material_id批量下载结构并写入CIF文件。\n"
            "参考tutorial.ipynb的方式：使用mp-api的MPRester拉取structure。"
        )
    )
    parser.add_argument("csv", help="包含material_id列的CSV文件路径")
    parser.add_argument("--column", default="material_id", help="material_id列名（默认：material_id）")
    parser.add_argument("--outdir", default="cif/mp_v2-way3", help="输出目录（默认：cif）")
    parser.add_argument(
        "--api-key",
        default="fFtrdShVJH4jwWHiId8v4cyGzV2oYnoG",
        help="Materials Project API key（默认从环境变量MP_API_KEY读取）",
    )
    parser.add_argument("--chunk-size", type=int, default=100, help="每次请求的material_id数量（默认：100）")
    parser.add_argument("--sleep", type=float, default=0.0, help="每个chunk之间休眠秒数（默认：0）")
    parser.add_argument("--skip-existing", action="store_true", help="若目标cif已存在则跳过")
    parser.add_argument(
        "--conventional",
        action="store_true",
        help="写出常规晶胞（conventional standard structure，tutorial.ipynb同款）",
    )
    parser.add_argument(
        "--symprec",
        type=float,
        default=0.01,
        help="SpacegroupAnalyzer的symprec（仅在--conventional时生效，默认：0.01）",
    )
    parser.add_argument("--limit", type=int, default=0, help="只下载前N个（用于测试，默认：0表示不限制）")
    parser.add_argument("--report", default="download_report.csv", help="下载结果报告CSV（默认：download_report.csv）")

    args = parser.parse_args(argv)

    csv_path = Path(args.csv)
    if not csv_path.is_file():
        print(f"CSV文件不存在：{csv_path}", file=sys.stderr)
        return 2

    api_key = args.api_key or os.environ.get("MP_API_KEY", "").strip()
    if not api_key:
        api_key = _load_api_key_from_dotenv(Path(".env")).strip()
    if not api_key:
        print(
            "缺少Materials Project API key：请设置环境变量`MP_API_KEY`、传入`--api-key`，或在当前目录创建`.env`并写入`MP_API_KEY=...`。",
            file=sys.stderr,
        )
        return 2

    material_ids = _read_material_ids(csv_path, args.column)
    if args.limit and args.limit > 0:
        material_ids = material_ids[: args.limit]

    if not material_ids:
        print("未读取到任何material_id。", file=sys.stderr)
        return 2

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    MPRester, CifWriter, SpacegroupAnalyzer = _require_mp_api_and_pymatgen()

    results: list[DownloadResult] = []

    chunks = _chunked(material_ids, args.chunk_size)
    total = len(material_ids)
    downloaded = 0

    with MPRester(api_key) as mpr:
        for chunk_idx, chunk in enumerate(chunks, start=1):
            if args.sleep and chunk_idx > 1:
                time.sleep(args.sleep)

            docs = mpr.materials.summary.search(
                material_ids=chunk,
                fields=["material_id", "structure"],
            )

            fetched = {doc.material_id: doc.structure for doc in docs}

            for mid in chunk:
                target = outdir / f"{mid}.cif"
                if args.skip_existing and target.exists():
                    results.append(
                        DownloadResult(material_id=mid, path=str(target), status="skipped", error="")
                    )
                    continue

                structure = fetched.get(mid)
                if structure is None:
                    results.append(
                        DownloadResult(material_id=mid, path=str(target), status="missing", error="not found")
                    )
                    continue

                try:
                    if args.conventional:
                        analyzer = SpacegroupAnalyzer(structure, symprec=args.symprec)
                        structure = analyzer.get_conventional_standard_structure()

                    CifWriter(structure).write_file(str(target))
                    downloaded += 1
                    results.append(
                        DownloadResult(material_id=mid, path=str(target), status="ok", error="")
                    )
                except Exception as exc:
                    results.append(
                        DownloadResult(
                            material_id=mid,
                            path=str(target),
                            status="error",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )

            done = chunk_idx * args.chunk_size
            done = min(done, total)
            print(f"[{done}/{total}] 已处理chunk {chunk_idx}/{len(chunks)}，已写出 {downloaded} 个CIF")

    report_path = Path(args.report)
    with report_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["material_id", "path", "status", "error"])
        for r in results:
            writer.writerow([r.material_id, r.path, r.status, r.error])

    print(f"完成：CIF输出目录={outdir}；报告={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
