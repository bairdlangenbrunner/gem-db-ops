#!/usr/bin/env python3
"""
gem_sheets.py — read-only pulls from GEM's *other* backend: Google Sheets.

Why this exists alongside gem_query.py
--------------------------------------
Most GEM trackers live in the Postgres project database (see gem_query.py).
The pipeline trackers do not: GGIT's gas pipelines and GOIT's oil/NGL pipelines
have never been migrated, and `plant."projectType"` has no pipeline value — the
authoritative data is still the "Pipelines (Gas/Oil/NGL) - main" spreadsheet.
So this repo has two read backends, and this module is the Sheets one.

  gem_query.py   Postgres  -> lng/, gogpt/, goget/
  gem_sheets.py  Sheets    -> ggit/, goit/  (+ the shared operators/owners tab)

Access rules (non-negotiable)
-----------------------------
* AUTHENTICATED READS ONLY, via the `gws` CLI with the read-only work profile
  `~/.config/gws-gem`. Anonymous/public endpoints — `export?format=csv&gid=`,
  gviz `tq?tqx=out:csv`, `/pub`, `/htmlview` — began 401ing on 2026-07-29 by
  design as public link access is withdrawn. They are NOT a fallback to keep
  warm; never reintroduce one here or in a consumer.
* Read-only by construction: this module refuses to run against the
  `gws-gem-write` profile, and exposes no write call. Sheet *writes* live in
  `goit-ggit-data-ops/route-lengths/` (sheet_writer.py + sheets_client.py) and
  stay there.
* Laptop-only. The gem-analysis service account was deleted 2026-07-31, so
  there is no CI/headless credential — these pulls are run by hand. If gws
  fails with an auth error, the fix is an interactive `gws-gem auth login`
  (needs a browser).

Row-offset contract
-------------------
Values are read FORMATTED_VALUE, exactly what the retired CSV export produced,
and the sheet's preamble rows are preserved, so the header-row offsets the whole
pipelines ecosystem depends on keep working:

    Gas pipelines             header at 0-indexed CSV row 2  (load with header=2)
    Oil/NGL pipelines         header at 0-indexed CSV row 2  (load with header=2)
    Pipeline operators/owners header at 0-indexed CSV row 1  (load with header=1)

Rows are right-padded to the widest row because the values API truncates
trailing empty cells per row while the old CSV export padded them.
Verified 2026-07-29 against the last anonymous-export snapshots: identical
column lists and identical row counts on all three tabs.

CLI
---
    python gem_sheets.py --list-tabs
    python gem_sheets.py --tab ggit -o data/GGIT_gas.csv
    python gem_sheets.py --tab "Hydrogen pipelines" -o data/h2.csv --header-row 2
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# "Pipelines (Gas/Oil/NGL) - main" — the pipeline trackers' backend sheet.
PIPELINES_SHEET_KEY = "1foPLE6K-uqFlaYgLPAUxzeXfDO5wOOqE7tibNHeqTek"

# gws profile holding the work account's READ-ONLY scopes. Override for an
# alternate read profile only; a write profile is rejected (see build_env()).
CONFIG_DIR_ENV_VAR = "GEM_SHEETS_GWS_CONFIG_DIR"
DEFAULT_CONFIG_DIR = "~/.config/gws-gem"


@dataclass(frozen=True)
class SheetTab:
    """A pullable tab: where it is, how to read it, what to call the output."""

    key: str                 # short name used on the CLI and by the pull scripts
    title: str               # exact tab title (Sheets values.get takes a title)
    sheet_key: str           # spreadsheet id
    header_row: int          # 0-indexed row of the header in the written CSV
    default_output: str      # default filename
    gid: str                 # tab gid — for cross-referencing docs/URLs only
    description: str


# The tab registry. `gid` is recorded because docs and older URLs elsewhere
# identify tabs by gid; the pull itself always addresses tabs BY TITLE.
TABS: dict[str, SheetTab] = {
    "ggit": SheetTab(
        key="ggit",
        title="Gas pipelines",
        sheet_key=PIPELINES_SHEET_KEY,
        header_row=2,
        default_output="GGIT_gas.csv",
        gid="1020144097",
        description="GGIT gas pipelines (132 cols). NB: GGIT's LNG terminals are "
                    "NOT here — they're in Postgres, pulled by lng/pull.py.",
    ),
    "goit": SheetTab(
        key="goit",
        title="Oil/NGL pipelines",
        sheet_key=PIPELINES_SHEET_KEY,
        header_row=2,
        default_output="GOIT_oil_ngl.csv",
        gid="456134080",
        description="GOIT oil & NGL pipelines (107 cols).",
    ),
    "pipeline_owners": SheetTab(
        key="pipeline_owners",
        title="Pipeline operators/owners",
        sheet_key=PIPELINES_SHEET_KEY,
        header_row=1,
        default_output="GEM_pipeline_operators_owners.csv",
        gid="1489950650",
        description="ProjectID-keyed operators/owners for both pipeline trackers; "
                    "holds the Owner [ref] / Operator [ref] source columns the "
                    "tracker tabs don't.",
    ),
    "hydrogen": SheetTab(
        key="hydrogen",
        title="Hydrogen pipelines",
        sheet_key=PIPELINES_SHEET_KEY,
        header_row=2,
        default_output="GEM_hydrogen_pipelines.csv",
        gid="1588190855",
        description="Hydrogen pipelines (same backend sheet, separate tracker).",
    ),
}


class SheetsError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# gws plumbing
# ---------------------------------------------------------------------------

def config_dir() -> str:
    return os.path.expanduser(os.environ.get(CONFIG_DIR_ENV_VAR) or DEFAULT_CONFIG_DIR)


def build_env() -> dict:
    """Env for the gws subprocess: read-only profile + file keyring backend."""
    path = config_dir()
    if not os.path.isdir(path):
        raise SheetsError(
            f"gws config dir not found: {path}\n"
            "Expected the profile set up by the `gws-gem` shell wrapper.\n"
            "See README.md > Google Sheets backend for setup."
        )
    # This module is read-only by construction; refuse a write-scoped profile
    # outright rather than trust that no write call is ever added later.
    if "write" in os.path.basename(path.rstrip("/")):
        raise SheetsError(
            f"refusing to use a write-scoped gws profile ({path}). gem_sheets.py "
            "is read-only; sheet writes belong in "
            "goit-ggit-data-ops/route-lengths/."
        )
    return dict(
        os.environ,
        GOOGLE_WORKSPACE_CLI_CONFIG_DIR=path,
        GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND="file",
    )


def _run_gws(argv: list[str], what: str) -> dict:
    try:
        proc = subprocess.run(
            ["gws", "sheets"] + argv,
            capture_output=True, text=True, env=build_env(),
        )
    except FileNotFoundError:
        raise SheetsError(
            "the `gws` CLI is not on PATH. Install it with "
            "`brew install google-workspace-cli` (see README.md > "
            "Google Sheets backend)."
        ) from None
    if proc.returncode != 0:
        raise SheetsError(
            f"{what} failed (exit {proc.returncode}): "
            f"{(proc.stderr.strip() or proc.stdout.strip())[:400]}\n"
            "If this is an auth error, run `gws-gem auth login` (needs a browser)."
        )
    # gws prints a keyring banner ahead of the JSON body on some paths, so slice
    # from the first brace rather than json.loads-ing the whole stream.
    out = proc.stdout
    brace = out.find("{")
    if brace < 0:
        raise SheetsError(f"{what}: no JSON in gws output: {out[:200]!r}")
    try:
        body = json.loads(out[brace:])
    except json.JSONDecodeError as exc:
        raise SheetsError(f"{what}: gws returned non-JSON: {out[brace:brace + 400]!r}") from exc
    # gws reports API errors as JSON on stdout with an "error" key and still
    # exits 0, so check the body even on a clean return code.
    if isinstance(body, dict) and "error" in body:
        raise SheetsError(f"{what}: Sheets API error: {body['error']}")
    return body


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def list_tabs(sheet_key: str = PIPELINES_SHEET_KEY) -> list[dict]:
    """Every tab in the spreadsheet: title, gid, grid size, frozen rows."""
    body = _run_gws(
        ["spreadsheets", "get", "--params", json.dumps({
            "spreadsheetId": sheet_key,
            "fields": "sheets.properties(sheetId,title,index,gridProperties)",
        })],
        "spreadsheets get",
    )
    out = []
    for sheet in body.get("sheets", []):
        props = sheet.get("properties", {})
        grid = props.get("gridProperties", {})
        out.append({
            "gid": str(props.get("sheetId")),
            "title": props.get("title"),
            "index": props.get("index"),
            "rows": grid.get("rowCount"),
            "columns": grid.get("columnCount"),
            "frozen_rows": grid.get("frozenRowCount", 0),
        })
    return out


def read_tab_values(title: str, sheet_key: str = PIPELINES_SHEET_KEY) -> list[list[str]]:
    """Raw FORMATTED_VALUE rows for a whole tab, preamble rows included."""
    body = _run_gws(
        ["spreadsheets", "values", "get", "--params", json.dumps({
            "spreadsheetId": sheet_key,
            "range": f"'{title}'",
            "valueRenderOption": "FORMATTED_VALUE",
            "majorDimension": "ROWS",
        })],
        f"values get {title!r}",
    )
    values = body.get("values")
    if not values:
        raise SheetsError(
            f"no values returned for {title!r} — wrong tab title, or the token "
            "expired (run `gws-gem auth login`)."
        )
    return values


def write_values_to_csv(values: list[list[str]], out_path) -> tuple[int, int]:
    """Write rows to CSV, right-padded to the widest row. Returns (rows, cols)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    width = max(len(r) for r in values)
    with open(out_path, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(
            [str(c) for c in row] + [""] * (width - len(row)) for row in values
        )
    return len(values), width


def pull_tab(tab: SheetTab, out_path) -> tuple[int, int]:
    """Pull one registered tab to CSV. Returns (rows written, columns)."""
    return write_values_to_csv(read_tab_values(tab.title, tab.sheet_key), out_path)


def resolve_tab(name: str) -> SheetTab:
    """Accept a registry key ('ggit') or an exact tab title ('Gas pipelines')."""
    if name in TABS:
        return TABS[name]
    for tab in TABS.values():
        if tab.title.lower() == name.lower():
            return tab
    raise SheetsError(
        f"unknown tab {name!r}. Registered keys: {', '.join(TABS)}. "
        "For an unregistered tab, pass its exact title plus --header-row."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Read-only pulls from the GEM pipelines backend spreadsheet.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Registered tabs:\n" + "\n".join(
            f"  {t.key:16} {t.title!r:30} header row {t.header_row}" for t in TABS.values()
        ),
    )
    p.add_argument("--list-tabs", action="store_true",
                   help="List every tab in the backend sheet and exit")
    p.add_argument("--tab", help="Registry key (ggit/goit/pipeline_owners/hydrogen) "
                                 "or an exact tab title")
    p.add_argument("-o", "--output", type=Path,
                   help="Output CSV (default: the tab's default_output in cwd)")
    p.add_argument("--sheet-key", default=PIPELINES_SHEET_KEY,
                   help="Spreadsheet id (default: the pipelines backend sheet)")
    p.add_argument("--header-row", type=int,
                   help="0-indexed header row, for an unregistered tab")
    args = p.parse_args(argv)

    try:
        if args.list_tabs:
            for t in list_tabs(args.sheet_key):
                print(f"{t['gid']:>12} | {t['title']!r:45} | "
                      f"{t['rows']}x{t['columns']} | frozen {t['frozen_rows']}")
            return 0

        if not args.tab:
            p.error("one of --list-tabs or --tab is required")

        try:
            tab = resolve_tab(args.tab)
        except SheetsError:
            if args.header_row is None:
                raise
            tab = SheetTab(key=args.tab, title=args.tab, sheet_key=args.sheet_key,
                           header_row=args.header_row,
                           default_output=f"{args.tab.replace('/', '_')}.csv",
                           gid="", description="ad-hoc tab")

        out = args.output or Path(tab.default_output)
        rows, cols = pull_tab(tab, out)
        header_row = args.header_row if args.header_row is not None else tab.header_row
        print(f"{rows} rows x {cols} cols -> {out}  (header at 0-indexed row {header_row})")
        return 0
    except SheetsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
