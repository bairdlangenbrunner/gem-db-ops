# gem-db-ops

Standalone repo for pulling fresh read-only CSV exports from the GEM project
database. `README.md` has the full layout and setup; the short version:

- "pull the fresh LNG export" → `python lng/pull.py` → `lng/gem_export.csv` +
  `lng/gem_export.colmap.json`.
- "pull GOGPT" → `python gogpt/pull.py` → `gogpt/gem_export_gogpt.csv` +
  colmap. The export contains every combustion unit (oil+gas+coal+bio), same
  as the website's GOGPT export.
- "pull GOGET" → `python goget/pull.py` → `goget/gem_export_goget_tables/`
  (one CSV per table + manifest; no flat all-fields exporter exists for GOGET;
  `plant_history` excluded unless `--include-history`). Soft-deleted records
  are kept and marked: child CSVs get appended `plant_deleted` /
  `plant_deletedTimestamp` columns propagated from `plant.deleted`
  (`--mark-only` re-runs just that pass).

All pulls read the read-only Postgres (`GEM_READONLY_DB_URL`).

Rules:

- **Never write to the GEM database.** Everything here is read-only exports.
- **Never commit credentials or pulled CSVs** (both gitignored).
- **`gem_export_via_web.py` is NOT in use** — the cookie-based website export
  path is disconnected everywhere (kept for reference only). Do not invoke it
  or wire it back into a pull path without asking the user.
- After a pull, sanity-check the CSV actually refreshed (mtime + row count)
  and report the row/column counts.
- `gem_all_fields.py` run directly is a silent no-op — always pull via a
  `pull.py` or `gem_query.py --all-fields`.
- These scripts are shared with `../lng-terminals-researcher/scripts/` — a bug
  fix in `gem_query.py` / `gem_all_fields.py` / `gem_export_via_web.py` should
  be mirrored there too.
