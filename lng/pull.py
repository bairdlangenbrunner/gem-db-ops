#!/usr/bin/env python3
"""
Pull the current LNG terminals "all-fields" CSV from the GEM database and
derive the column-index map from the header row.

Reads directly from the read-only Postgres (no cookies) via ../gem_query.py's
engine + ../gem_all_fields.py's exporter. Requires:

    export GEM_READONLY_DB_URL='postgres://readonly:PASSWORD@HOST:5432/DBNAME'

(The cookie-based website exporter ../gem_export_via_web.py is NOT in use —
kept for reference only; do not wire it back in without asking the user.)

Usage (from this folder or anywhere):
    python pull.py                      # fresh lng/gem_export.csv + .colmap.json
    python pull.py --output my.csv      # custom path
    python pull.py --map-only           # skip fetch; derive map from existing CSV
    python pull.py --limit 30           # small sample (plant limit, for testing)

Why re-derive the column map every pull: the all-fields export is ~115 columns
but the schema can drift between GEM database revisions (columns added,
renamed, reordered). Hard-coding offsets breaks silently; the derived map is
saved next to the CSV so downstream tooling reads the same one.

This is GGIT's LNG-terminals half. GGIT's **gas pipelines** are a different
backend and a different pull — see ../ggit/pull.py.

The expected-column map and the derive/report/save logic live in
../gem_colmap.py so every tracker pull (and every consumer repo) uses one copy.
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import gem_colmap  # noqa: E402

DEFAULT_OUT = HERE / "gem_export.csv"

# Canonical short name -> expected header text. Defined in ../gem_colmap.py;
# aliased here because that's where callers have always looked for it.
EXPECTED_COLUMNS = gem_colmap.LNG_EXPECTED_COLUMNS


def pull_postgres(out_path: Path, limit=None):
    """Flat all-fields export straight from the read-only Postgres."""
    from gem_query import get_database_url, build_engine, DEFAULT_STATEMENT_TIMEOUT_MS
    from gem_all_fields import export_all_fields

    engine = build_engine(get_database_url(), DEFAULT_STATEMENT_TIMEOUT_MS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = export_all_fields(engine, str(out_path), limit)
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
