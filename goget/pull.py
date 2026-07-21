#!/usr/bin/env python3
"""
Pull the current GOGET (oil & gas extraction) tables from the GEM database.

Cookie-free multi-table export from the read-only Postgres via
../gem_query.py --project-type goget: one CSV per table (plant, goget_project,
status_timeline, owners, reserves_production, ...) plus a _manifest.csv —
NOT a single flat file. Requires:

    export GEM_READONLY_DB_URL='postgres://readonly:PASSWORD@HOST:5432/DBNAME'

The multi-GB plant_history audit table is excluded by default
(--include-history to add it).

There is no flat "all-fields" CSV path for GOGET right now: ../gem_all_fields.py
covers only lng + gogpt, and the cookie-based website exporter
../gem_export_via_web.py is NOT in use (kept for reference only; do not wire
it back in without asking the user). If a flat goget exporter is needed, port
one into gem_all_fields.py following the lng/gogpt pattern and validate against
a fresh website export (see docs/ALL_FIELDS_STATUS.md).

Usage:
    python pull.py                      # -> goget/gem_export_goget_tables/*.csv
    python pull.py --output my_dir      # custom output directory
    python pull.py --include-history    # also export plant_history (multi-GB)
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

DEFAULT_TABLES_DIR = HERE / "gem_export_goget_tables"


def pull_tables(out_dir: Path, include_history=False):
    cmd = [sys.executable, str(ROOT / "gem_query.py"),
           "--project-type", "goget", "-o", str(out_dir)]
    if not include_history:
        cmd += ["--exclude", "plant_history"]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"ERROR: gem_query.py failed with exit code {result.returncode}")


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--output", "--out", dest="out", type=Path, default=DEFAULT_TABLES_DIR,
                   help="Output DIRECTORY (one CSV per table)")
    p.add_argument("--include-history", action="store_true",
                   help="Also export the multi-GB plant_history audit table")
    args = p.parse_args()
    pull_tables(args.out, include_history=args.include_history)


if __name__ == "__main__":
    main()
