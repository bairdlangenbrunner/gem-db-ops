# gem-database-access

Standalone tooling for pulling fresh CSV exports from the GEM project database
(read-only), for three trackers:

| Folder | Tracker | Pull command | Output |
|---|---|---|---|
| `lng/` | LNG terminals (GGIT-LNG) | `python lng/pull.py` | flat 115-col all-fields CSV + colmap |
| `gogpt/` | Oil & gas power plants (GOGPT) | `python gogpt/pull.py` | flat 86-col all-fields CSV + colmap |
| `goget/` | Oil & gas extraction (GOGET) | `python goget/pull.py` | one CSV per table + manifest |

All pulls read the **read-only Postgres** directly — no cookies, no website.
`lng` and `gogpt` write the fresh CSV **into their own folder** plus a
`.colmap.json` header→index map derived from the actual header row (never
hard-code column offsets — the schema drifts between GEM database revisions).
`goget` has no flat all-fields exporter yet, so its pull is a multi-table
export (`plant_history` excluded by default — it's multi-GB). The goget pull
keeps soft-deleted records (GOGET deletes at the plant level; rows stay in
Postgres with `plant.deleted` set) and propagates the flag into every child
CSV as appended `plant_deleted` / `plant_deletedTimestamp` columns.

## Setup

```bash
pip install -r requirements.txt
export GEM_READONLY_DB_URL='postgres://readonly:PASSWORD@HOST:5432/DBNAME'
```

(A gitignored `.env` works too if your shell loads it — never commit
credentials.)

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
  endpoints. **NOT IN USE** — nothing invokes it; kept for reference only. Do
  not wire it back into any pull path without asking.

## Notes

- Everything here is **read-only** against the GEM database: the Postgres role
  is `readonly` and sessions additionally set
  `default_transaction_read_only=on`.
- Pulled CSVs and colmaps are gitignored — this repo versions the tooling,
  not data snapshots.
- `archive/` (gitignored) holds pre-restructure May-2026 export snapshots;
  delete it whenever.
- The LNG research workflow lives in `../lng-terminals-researcher`, which
  keeps its own copies of these scripts under `scripts/`; if you fix a bug in
  the shared engine code, mirror it in both places.
