#!/usr/bin/env python3
"""
Pull the fresh GGIT **gas pipelines** export.

    python ggit/pull.py                 # -> ggit/gem_export_ggit.csv + .colmap.json
    python ggit/pull.py --with-owners   # + ggit/gem_export_pipeline_owners.csv
    python ggit/pull.py --map-only      # re-derive the colmap from the CSV on disk

Backend: the "Pipelines (Gas/Oil/NGL) - main" spreadsheet, tab "Gas pipelines",
read authenticated and read-only through gem_sheets.py (gws, ~/.config/gws-gem).
Gas pipelines are not in the Postgres project database, which is why this pull
goes to Sheets rather than gem_query.py.

NB: **GGIT's LNG terminals are a different pull.** They live in Postgres
(projectType 8) — use `python lng/pull.py`. This script is gas pipelines only.

The header lands at 0-indexed CSV row 2 (two preamble rows above it), matching
what the retired CSV export produced; read with `header=2` or via the colmap.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gem_pipeline_pull  # noqa: E402

if __name__ == "__main__":
    sys.exit(gem_pipeline_pull.main("ggit"))
