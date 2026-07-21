#!/usr/bin/env python3
"""
Pull the current GOGET (oil & gas extraction) export from the GEM database and
derive a header→index column map.

Unlike LNG and GOGPT, no flat "all-fields" Postgres exporter has been built
for GOGET yet (../gem_all_fields.py covers only lng + gogpt). Two paths:

Default path (--via-web is implied for the flat CSV): cookie-based download of
the website's "All GOGET" CSV via ../gem_export_via_web.py. Requires
GEM_PROJECT_DB_SESSIONID and GEM_PROJECT_DB_CSRFTOKEN (see that script's
docstring for the cookie extraction procedure).

Alternative (--tables): cookie-free multi-table Postgres export via
../gem_query.py --project-type goget — one CSV per table (plant, goget_project,
status_timeline, owners, ...) plus a _manifest.csv, NOT a single flat file.
Requires GEM_READONLY_DB_URL. If a flat goget exporter is ever needed, port it
into gem_all_fields.py following the lng/gogpt pattern and validate against a
fresh website export (see docs/ALL_FIELDS_STATUS.md).

Usage:
    python pull.py                      # website CSV -> goget/gem_export_goget.csv + .colmap.json
    python pull.py --output my.csv      # custom path
    python pull.py --map-only           # skip fetch; derive map from existing CSV
    python pull.py --tables             # Postgres multi-table export -> goget/gem_export_goget_tables/
"""
import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

DEFAULT_OUT = HERE / "gem_export_goget.csv"
DEFAULT_TABLES_DIR = HERE / "gem_export_goget_tables"


def pull_via_web(out_path: Path):
    """Flat 'All GOGET' CSV from the project-DB website (cookie auth)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(ROOT / "gem_export_via_web.py"), "goget", "-o", str(out_path)],
    )
    if result.returncode != 0:
        sys.exit(f"ERROR: gem_export_via_web.py failed with exit code {result.returncode}")
    size = out_path.stat().st_size
    if size < 1000:
        sys.exit(f"ERROR: CSV suspiciously small ({size} bytes) — verify auth and try again")


def pull_tables(out_dir: Path, include_history=False):
    """Cookie-free multi-table Postgres export (one CSV per table + manifest).
    plant_history is excluded by default — it's a multi-GB audit table."""
    cmd = [sys.executable, str(ROOT / "gem_query.py"),
           "--project-type", "goget", "-o", str(out_dir)]
    if not include_history:
        cmd += ["--exclude", "plant_history"]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"ERROR: gem_query.py failed with exit code {result.returncode}")


def derive_column_map(csv_path: Path):
    """Read header row, return {header: 0-indexed-column}. Re-derived every pull
    so downstream code never hard-codes offsets."""
    with open(csv_path, encoding="utf-8") as f:
        try:
            header = next(csv.reader(f))
        except StopIteration:
            sys.exit(f"ERROR: empty CSV at {csv_path}")
    if header and header[0].startswith("\ufeff"):
        header[0] = header[0][1:]
    return {
        "_total_columns": len(header),
        "columns": {h.strip(): i for i, h in enumerate(header)},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--output", "--out", dest="out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--map-only", action="store_true",
                   help="Skip the fetch; just derive the map from an existing CSV")
    p.add_argument("--tables", action="store_true",
                   help="Postgres multi-table export instead of the flat website CSV")
    p.add_argument("--include-history", action="store_true",
                   help="With --tables: also export the multi-GB plant_history audit table")
    args = p.parse_args()

    if args.tables:
        pull_tables(DEFAULT_TABLES_DIR if args.out == DEFAULT_OUT else args.out,
                    include_history=args.include_history)
        return

    if not args.map_only:
        pull_via_web(args.out)

    col_map = derive_column_map(args.out)
    map_path = args.out.with_suffix(".colmap.json")
    map_path.write_text(json.dumps(col_map, indent=2))
    print(f"  {col_map['_total_columns']} columns; column map saved to {map_path}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
