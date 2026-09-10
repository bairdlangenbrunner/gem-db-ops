#!/usr/bin/env python3
"""
gem_pipeline_pull.py — shared implementation behind ggit/pull.py and goit/pull.py.

The two pipeline trackers come out of the same backend spreadsheet, differ only
in which tab they read and which expected-column map they check against, and
both want the same shared operators/owners tab. So the pull logic lives here
once and the per-tracker scripts are one call each.

Not meant to be run directly — use `python ggit/pull.py` or `python goit/pull.py`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gem_colmap  # noqa: E402
import gem_sheets  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent

# tracker key -> (output dir, output filename)
DEFAULT_OUTPUTS = {
    "ggit": ("ggit", "gem_export_ggit.csv"),
    "goit": ("goit", "gem_export_goit.csv"),
}
OWNERS_FILENAME = "gem_export_pipeline_owners.csv"


def default_output(tracker: str) -> Path:
    subdir, name = DEFAULT_OUTPUTS[tracker]
    return REPO_ROOT / subdir / name


def _colmap_for(csv_path: Path, tracker: str, header_row: int) -> dict:
    expected = gem_colmap.EXPECTED_COLUMNS_BY_TRACKER[tracker]
    return gem_colmap.derive_report_save(csv_path, expected, header_row=header_row)


def _pull_one(tab: gem_sheets.SheetTab, out_path: Path, tracker: str) -> dict:
    print(f"\n=== {tab.title} -> {out_path} ===")
    rows, cols = gem_sheets.pull_tab(tab, out_path)
    data_rows = max(rows - (tab.header_row + 1), 0)
    print(f"  {rows} sheet rows x {cols} cols "
          f"({data_rows} data rows below the header at 0-indexed row {tab.header_row})")
    return _colmap_for(out_path, tracker, tab.header_row)


def main(tracker: str, argv: list[str] | None = None) -> int:
    tab = gem_sheets.TABS[tracker]
    owners_tab = gem_sheets.TABS["pipeline_owners"]

    p = argparse.ArgumentParser(
        description=f"Pull the live {tracker.upper()} export ({tab.title!r}) from the "
                    "GEM pipelines backend sheet, read-only.",
        epilog=f"Header lands at 0-indexed CSV row {tab.header_row} — read it with "
               f"pandas.read_csv(..., header={tab.header_row}) or via the "
               ".colmap.json written alongside.",
    )
    p.add_argument("-o", "--output", "--out", dest="output", type=Path,
                   default=default_output(tracker),
                   help=f"Output CSV (default: {default_output(tracker)})")
    p.add_argument("--with-owners", action="store_true",
                   help=f"Also pull {owners_tab.title!r} next to the tracker CSV "
                        "(ProjectID-keyed Owner/Operator [ref] columns)")
    p.add_argument("--owners-output", type=Path,
                   help=f"Where to write the owners tab (default: {OWNERS_FILENAME} "
                        "beside the tracker CSV)")
    p.add_argument("--map-only", action="store_true",
                   help="Skip the pull; re-derive the .colmap.json from the CSV on disk")
    args = p.parse_args(argv)

    out = args.output.resolve()

    try:
        if args.map_only:
            if not out.exists():
                print(f"ERROR: {out} does not exist — run without --map-only first.",
                      file=sys.stderr)
                return 1
            print(f"=== map-only: {out} ===")
            _colmap_for(out, tracker, tab.header_row)
            return 0

        col_map = _pull_one(tab, out, tracker)

        if args.with_owners:
            owners_out = (args.owners_output or out.parent / OWNERS_FILENAME).resolve()
            _pull_one(owners_tab, owners_out, "pipeline_owners")

        gone = gem_colmap.missing(
            col_map, gem_colmap.EXPECTED_COLUMNS_BY_TRACKER[tracker])
        print(f"\nDone: {out}")
        if gone:
            print(f"  NOTE: {len(gone)} expected columns missing — see the warning "
                  "above before trusting downstream offsets.")
        return 0
    except gem_sheets.SheetsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
