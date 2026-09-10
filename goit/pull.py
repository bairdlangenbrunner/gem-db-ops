#!/usr/bin/env python3
"""
Pull the fresh GOIT **oil / NGL pipelines** export.

    python goit/pull.py                 # -> goit/gem_export_goit.csv + .colmap.json
    python goit/pull.py --with-owners   # + goit/gem_export_pipeline_owners.csv
    python goit/pull.py --map-only      # re-derive the colmap from the CSV on disk

Backend: the "Pipelines (Gas/Oil/NGL) - main" spreadsheet, tab "Oil/NGL
pipelines", read authenticated and read-only through gem_sheets.py (gws,
~/.config/gws-gem). Oil/NGL pipelines are not in the Postgres project database,
which is why this pull goes to Sheets rather than gem_query.py.

The header lands at 0-indexed CSV row 2 (two preamble rows above it), matching
what the retired CSV export produced; read with `header=2` or via the colmap.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gem_pipeline_pull  # noqa: E402

if __name__ == "__main__":
    sys.exit(gem_pipeline_pull.main("goit"))
