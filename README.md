# gem-database-access

Standalone tooling for pulling fresh CSV exports from the GEM project database
(read-only), for three trackers:

| Folder | Tracker | Pull command | Primary path |
|---|---|---|---|
| `lng/` | LNG terminals (GGIT-LNG) | `python lng/pull.py` | Postgres (no cookies) |
| `gogpt/` | Oil & gas power plants (GOGPT) | `python gogpt/pull.py` | Postgres (no cookies) |
| `goget/` | Oil & gas extraction (GOGET) | `python goget/pull.py` | Website (cookie auth) |

Each `pull.py` writes the fresh CSV **into its own folder** (e.g.
`lng/gem_export.csv`) plus a `.colmap.json` header→index map derived from the
actual header row (never hard-code column offsets — the schema drifts between
GEM database revisions).

## Setup

```bash
pip install -r requirements.txt
```

Two auth mechanisms, set as environment variables (a gitignored `.env` works
too if your shell loads it — never commit credentials):

1. **Read-only Postgres** (primary for lng/gogpt; no expiry):

   ```bash
   export GEM_READONLY_DB_URL='postgres://readonly:PASSWORD@HOST:5432/DBNAME'
   ```

2. **Website session cookies** (goget's flat CSV; fallback for lng/gogpt via
   `--via-web`). Log into the GEM project DB in your browser, copy the
   `sessionid` and `csrftoken` cookies from DevTools → Application → Cookies:

   ```bash
   export GEM_PROJECT_DB_SESSIONID='...'
   export GEM_PROJECT_DB_CSRFTOKEN='...'
   ```

   Cookies expire periodically — re-copy when a pull reports an auth failure.
   Full procedure in `gem_export_via_web.py`'s docstring.

## Shared code (repo root)

- `gem_query.py` — the engine: read-only Postgres connection, schema
  introspection, single-table / multi-table (FK-traversal) exports, and the
  `--all-fields {lng,gogpt}` dispatch. Works for ANY project type
  (`--project-type lng|combustion|goget|steel|...`).
- `gem_all_fields.py` — library reproducing the website's flat "Export all
  fields" CSVs from Postgres (LNG: 115 cols; GOGPT: 86 cols). **Running it
  directly is a no-op** — it's imported by `gem_query.py 
  --all-fields` and the per-tracker `pull.py` scripts. Validation notes:
  `docs/ALL_FIELDS_STATUS.md`. No GOGET exporter yet — port one here following
  the lng/gogpt pattern if needed.
- `gem_export_via_web.py` — cookie-based downloads of the website's own export
  endpoints (`lng`, `lng_export`, `goget`, `gogpt`, `both`, `all`).

## Notes

- Everything here is **read-only** against the GEM database: the Postgres role
  is `readonly` and sessions additionally set
  `default_transaction_read_only=on`; the website path only GETs export CSVs.
- Pulled CSVs and colmaps are gitignored — this repo versions the tooling,
  not data snapshots.
- `archive/` (gitignored) holds pre-restructure May-2026 export snapshots;
  delete it whenever.
- The LNG research workflow lives in `../lng-terminals-researcher`, which
  keeps its own copies of these scripts under `scripts/`; if you fix a bug in
  the shared engine code, mirror it in both places.
