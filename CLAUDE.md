# gem-database-access

Standalone repo for pulling fresh read-only CSV exports from the GEM project
database. `README.md` has the full layout and setup; the short version:

- "pull the fresh LNG export" → `python lng/pull.py` → `lng/gem_export.csv` +
  `lng/gem_export.colmap.json` (Postgres, needs `GEM_READONLY_DB_URL`; add
  `--via-web` for the cookie-based website fallback).
- "pull GOGPT" → `python gogpt/pull.py` → `gogpt/gem_export_gogpt.csv` +
  colmap (Postgres; `--via-web` fallback). The export contains every
  combustion unit (oil+gas+coal+bio), same as the website's GOGPT export.
- "pull GOGET" → `python goget/pull.py` → `goget/gem_export_goget.csv` +
  colmap (website cookie auth — needs `GEM_PROJECT_DB_SESSIONID` +
  `GEM_PROJECT_DB_CSRFTOKEN`; there is no flat Postgres exporter for GOGET
  yet). `--tables` instead does a cookie-free Postgres multi-table export.

Rules:

- **Never write to the GEM database.** Everything here is read-only exports.
- **Never commit credentials or pulled CSVs** (both gitignored). Auth env vars:
  `GEM_READONLY_DB_URL` (Postgres) / `GEM_PROJECT_DB_SESSIONID` +
  `GEM_PROJECT_DB_CSRFTOKEN` (website cookies; expired cookies → ask the user
  to re-copy them from the browser, don't attempt a headless login).
- After a pull, sanity-check the CSV actually refreshed (mtime + row count)
  and report the row/column counts.
- `gem_all_fields.py` run directly is a silent no-op — always pull via a
  `pull.py` or `gem_query.py --all-fields`.
- These scripts are shared with `../lng-terminals-researcher/scripts/` — a bug
  fix in `gem_query.py` / `gem_all_fields.py` / `gem_export_via_web.py` should
  be mirrored there too.
