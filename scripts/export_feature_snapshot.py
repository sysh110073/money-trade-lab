from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def export_snapshot(csv_path: Path, parquet_path: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    frame = pd.read_csv(csv_path)
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "csv_path": str(csv_path),
        "parquet_path": str(parquet_path),
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "latest_date": str(pd.to_datetime(frame["date"], errors="coerce").max().date()) if "date" in frame else "",
        "csv_hash": _sha256(csv_path),
        "parquet_hash": _sha256(parquet_path),
    }
    if manifest_path:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the compatibility CSV feature file to a Parquet snapshot.")
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=None)
    args = parser.parse_args()
    manifest = export_snapshot(args.csv, args.parquet, args.manifest)
    print(json.dumps({"status": "ok", **manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
