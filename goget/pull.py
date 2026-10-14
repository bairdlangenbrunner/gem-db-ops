#!/usr/bin/env python3
"""
Pull the current GOGET (oil & gas extraction) data from the GEM database.

Two outputs, both straight from the read-only Postgres (no cookies). Requires:

    export GEM_READONLY_DB_URL='postgres://readonly:PASSWORD@HOST:5432/DBNAME'

1. Flat "all-fields" CSV: goget/gem_export_goget.csv + .colmap.json, one row
   per project (every GOGET plant has exactly one unit), 46 columns. This is
   ../gem_all_fields.export_goget_all_fields, a port of the website's
   `all_goget` report (GEM-project-db projects/project_display.py). Note the
   website's naming: "Unit ID" / "Unit Name" are the PLANT id ('L' prefix) and
   plant name. Soft-deleted plants are excluded, as on the website.

2. Multi-table dump: goget/gem_export_goget_tables/, one CSV per table (plant,
   goget_project, status_timeline, owners, reserves_production, ...) plus a
   _manifest.csv, via ../gem_query.py --project-type goget. The multi-GB
   plant_history audit table is excluded by default (--include-history).
   Soft-deleted records are INCLUDED and marked: GOGET deletion happens at
   the plant level (`plant.deleted` / `plant.deletedTimestamp` — rows stay in
   Postgres), so a post-pull pass propagates the flag into every child CSV as
   two appended columns, `plant_deleted` / `plant_deletedTimestamp` (resolved
   via plant_id/project_id/projectComplex_id, or unit_id -> powerplant_unit ->
   plant, or thread_id -> thread -> plant). `public.plant.csv` itself already
   carries the native columns.

(The cookie-based website exporter ../gem_export_via_web.py is NOT in use —
kept for reference only; do not wire it back in without asking the user.)

Usage:
    python pull.py                      # both: flat CSV + colmap, then the tables
    python pull.py --flat-only          # just goget/gem_export_goget.csv + .colmap.json
    python pull.py --tables-only        # just goget/gem_export_goget_tables/
    python pull.py --output my.csv      # custom flat CSV path
    python pull.py --tables-dir my_dir  # custom tables directory
    python pull.py --limit 30           # small flat sample (plant cap, for testing)
    python pull.py --map-only           # skip fetching; derive the colmap from the existing CSV
    python pull.py --include-history    # also export plant_history (multi-GB)
    python pull.py --mark-only          # skip the pull; re-run just the deleted-flag pass

The expected-column map and the derive/report/save logic live in
../gem_colmap.py so every tracker pull (and every consumer repo) uses one copy.
"""
import argparse
import csv
import subprocess
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)  # notes fields exceed the 128KB default

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import gem_colmap  # noqa: E402

DEFAULT_OUT = HERE / "gem_export_goget.csv"
DEFAULT_TABLES_DIR = HERE / "gem_export_goget_tables"

# Canonical short name -> expected header text. Defined in ../gem_colmap.py.
EXPECTED_COLUMNS = gem_colmap.GOGET_EXPECTED_COLUMNS

# How a child row resolves to its plant(s), tried in this order. FK ground
# truth (pg_constraint, 2026-07-21): plant_id/project_id/projectComplex_id all
# reference plant.id; unit_id/powerplant_unit_id reference powerplant_unit.id;
# thread_id references thread.id (thread.project_id -> plant.id).
PLANT_LINK_COLS = ("plant_id", "project_id", "projectComplex_id")
UNIT_LINK_COLS = ("unit_id", "powerplant_unit_id")
THREAD_LINK_COLS = ("thread_id",)
MARK_COLS = ("plant_deleted", "plant_deletedTimestamp")


def pull_flat(out_path: Path, limit=None):
    """Flat all-fields export straight from the read-only Postgres."""
    from gem_query import get_database_url, build_engine, DEFAULT_STATEMENT_TIMEOUT_MS
    from gem_all_fields import export_goget_all_fields

    engine = build_engine(get_database_url(), DEFAULT_STATEMENT_TIMEOUT_MS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = export_goget_all_fields(engine, str(out_path), limit)
    print(f"  wrote {n:,} project rows to {out_path}", file=sys.stderr)


def pull_tables(out_dir: Path, include_history=False):
    cmd = [sys.executable, str(ROOT / "gem_query.py"),
           "--project-type", "goget", "-o", str(out_dir)]
    if not include_history:
        cmd += ["--exclude", "plant_history"]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"ERROR: gem_query.py failed with exit code {result.returncode}")


def _load_map(path: Path, key_col: str, val_cols):
    """{key: (val, ...)} from a CSV; missing file -> empty dict."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {row[key_col]: tuple(row[c] for c in val_cols) for row in reader}


def mark_deleted(out_dir: Path):
    """Append plant_deleted / plant_deletedTimestamp to every child CSV.

    GOGET soft-deletes live only on plant; child tables (status_timeline,
    goget_project, owners, ...) have no deleted column of their own, so a
    consumer of a child CSV can't tell which rows belong to deleted records.
    A row is marked deleted when EVERY plant it links to is deleted (a unit's
    own deleted flag also counts for unit-linked rows). Rows with no
    resolvable plant link get an empty value. Idempotent: already-marked
    files are rewritten from their original columns.
    """
    out_dir = Path(out_dir)
    plant = _load_map(out_dir / "public.plant.csv", "id",
                      ("deleted", "deletedTimestamp"))
    if not plant:
        sys.exit(f"ERROR: {out_dir}/public.plant.csv missing or empty — "
                 "run the pull first")
    unit = _load_map(out_dir / "public.powerplant_unit.csv", "id",
                     ("plant_id", "deleted", "deletedTimestamp"))
    thread = _load_map(out_dir / "public.thread.csv", "id", ("project_id",))

    def resolve(row, header_set):
        """-> ('True'|'False'|'', timestamp) for one row."""
        verdicts = []  # (deleted_bool, ts) per resolved link
        for c in PLANT_LINK_COLS:
            if c in header_set and row[c] and row[c] in plant:
                d, ts = plant[row[c]]
                verdicts.append((d == "True", ts))
        for c in UNIT_LINK_COLS:
            if c in header_set and row[c] and row[c] in unit:
                plant_id, u_del, u_ts = unit[row[c]]
                p_del, p_ts = plant.get(plant_id, ("False", ""))
                dead = p_del == "True" or u_del == "True"
                verdicts.append((dead, p_ts or u_ts))
        for c in THREAD_LINK_COLS:
            if c in header_set and row[c] and row[c] in thread:
                (plant_id,) = thread[row[c]]
                if plant_id in plant:
                    d, ts = plant[plant_id]
                    verdicts.append((d == "True", ts))
        if not verdicts:
            return "", ""
        if all(d for d, _ in verdicts):
            return "True", max(ts for _, ts in verdicts)
        return "False", ""

    for path in sorted(out_dir.glob("public.*.csv")):
        if path.name == "public.plant.csv":
            continue  # native deleted/deletedTimestamp columns already there
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = [h for h in (reader.fieldnames or []) if h not in MARK_COLS]
            if not header:
                continue
            header_set = set(header)
            if not any(c in header_set for c in
                       PLANT_LINK_COLS + UNIT_LINK_COLS + THREAD_LINK_COLS):
                continue  # no path back to plant — leave untouched
            tmp = path.with_suffix(".csv.tmp")
            n = dead = 0
            with open(tmp, "w", encoding="utf-8", newline="") as g:
                writer = csv.DictWriter(g, fieldnames=header + list(MARK_COLS),
                                        extrasaction="ignore")
                writer.writeheader()
                for row in reader:
                    row["plant_deleted"], row["plant_deletedTimestamp"] = \
                        resolve(row, header_set)
                    writer.writerow(row)
                    n += 1
                    dead += row["plant_deleted"] == "True"
            tmp.replace(path)
            print(f"  marked {path.name}: {n:,} rows, {dead:,} on deleted plants",
                  file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--output", "--out", dest="out", type=Path, default=DEFAULT_OUT,
                   help="Flat all-fields CSV path (default goget/gem_export_goget.csv)")
    p.add_argument("--tables-dir", type=Path, default=DEFAULT_TABLES_DIR,
                   help="Output DIRECTORY for the multi-table dump")
    which = p.add_mutually_exclusive_group()
    which.add_argument("--flat-only", action="store_true",
                       help="Only the flat CSV + colmap; skip the multi-table dump")
    which.add_argument("--tables-only", action="store_true",
                       help="Only the multi-table dump; skip the flat CSV")
    p.add_argument("--limit", type=int, help="Plant-count cap for the flat CSV (testing)")
    p.add_argument("--map-only", action="store_true",
                   help="Skip fetching; just derive the colmap from the existing flat CSV")
    p.add_argument("--include-history", action="store_true",
                   help="Also export the multi-GB plant_history audit table")
    p.add_argument("--mark-only", action="store_true",
                   help="Skip the table pull; just (re)run the deleted-flag pass")
    args = p.parse_args()

    do_flat = not args.tables_only
    do_tables = not args.flat_only and not args.map_only

    if do_flat:
        if not args.map_only:
            pull_flat(args.out, limit=args.limit)
        gem_colmap.derive_report_save(args.out, EXPECTED_COLUMNS)

    if do_tables:
        if not args.mark_only:
            pull_tables(args.tables_dir, include_history=args.include_history)
        mark_deleted(args.tables_dir)


if __name__ == "__main__":
    main()
