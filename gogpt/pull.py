#!/usr/bin/env python3
"""
Pull the current GOGPT (oil & gas power plants) "all-fields" CSV from the GEM
database and derive a header→index column map.

Reads directly from the read-only Postgres (no cookies) via ../gem_query.py's
engine + ../gem_all_fields.py's export_gogpt_all_fields. Requires:

    export GEM_READONLY_DB_URL='postgres://readonly:PASSWORD@HOST:5432/DBNAME'

Note: matching the website's behavior, the export contains EVERY
combustion-projectType unit (oil + gas + coal + bioenergy), not just
trackerSearch='GOGPT' rows — the site's ?tracker=GOGPT filter is cosmetic.
~34,500 rows, ~25 seconds.

(The cookie-based website exporter ../gem_export_via_web.py is NOT in use —
kept for reference only; do not wire it back in without asking the user.)

Usage:
    python pull.py                      # fresh gogpt/gem_export_gogpt.csv + .colmap.json
    python pull.py --output my.csv      # custom path
    python pull.py --map-only           # skip fetch; derive map from existing CSV
    python pull.py --limit 30           # small sample (plant limit, for testing)

The expected-column map and the derive/report/save logic live in
../gem_colmap.py so every tracker pull (and every consumer repo) uses one copy.
Since 2026-08-11 this colmap carries canonical short names and drift detection,
like the LNG one — it used to be a bare {header: index} map.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import gem_colmap  # noqa: E402

DEFAULT_OUT = HERE / "gem_export_gogpt.csv"

# Canonical short name -> expected header text. Defined in ../gem_colmap.py.
EXPECTED_COLUMNS = gem_colmap.GOGPT_EXPECTED_COLUMNS


def pull_postgres(out_path: Path, limit=None):
    """Primary path: flat all-fields export straight from the read-only Postgres."""
    from gem_query import get_database_url, build_engine, DEFAULT_STATEMENT_TIMEOUT_MS
    from gem_all_fields import export_gogpt_all_fields

    engine = build_engine(get_database_url(), DEFAULT_STATEMENT_TIMEOUT_MS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = export_gogpt_all_fields(engine, str(out_path), limit)
    print(f"  wrote {n:,} unit rows to {out_path}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--output", "--out", dest="out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--map-only", action="store_true",
                   help="Skip the fetch; just derive the map from an existing CSV")
    p.add_argument("--limit", type=int, help="Plant-count cap for testing")
    args = p.parse_args()

    if not args.map_only:
        pull_postgres(args.out, limit=args.limit)

    gem_colmap.derive_report_save(args.out, EXPECTED_COLUMNS)


if __name__ == "__main__":
    main()
