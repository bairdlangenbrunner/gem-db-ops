# gem-db-ops

The **single source of truth for pulling GEM tracker data** (read-only). Every
other repo — researcher repos, map builders, analysis scripts, dashboards —
calls into this one instead of keeping its own connection, pull, or
column-map code. If you find a duplicate pull path anywhere, delete it and
point at a command below (`docs/CONSUMERS.md` lists each consumer's canonical
command).

Two backends, five trackers:

| Folder | Tracker | Backend | Pull command | Output |
|---|---|---|---|---|
| `lng/` | LNG terminals (GGIT-LNG) | Postgres | `python lng/pull.py` | flat 115-col all-fields CSV + colmap |
| `gogpt/` | Oil & gas power plants (GOGPT) | Postgres | `python gogpt/pull.py` | flat 86-col all-fields CSV + colmap |
| `goget/` | Oil & gas extraction (GOGET) | Postgres | `python goget/pull.py` | one CSV per table + manifest |
| `ggit/` | Gas pipelines (GGIT) | Google Sheet | `python ggit/pull.py` | pipelines tab as CSV + colmap |
| `goit/` | Oil/NGL pipelines (GOIT) | Google Sheet | `python goit/pull.py` | pipelines tab as CSV + colmap |

**Why two backends:** the pipeline trackers are not in Postgres. `plant."projectType"`
has nine values (combustion, lng, goget, steel, …) and none of them are pipelines
— the pipeline backend is still the "Pipelines (Gas/Oil/NGL) - main" Google Sheet.
So GGIT-gas and GOIT come from Sheets, while LNG/GOGPT/GOGET come from Postgres.
Note the split inside GGIT: its **pipelines** are the Sheet (`ggit/pull.py`), its
**LNG terminals** are Postgres (`lng/pull.py`).

Both pipeline pulls take `--with-owners` to also pull the pipeline
operators/owners tab. Every CSV lands with a `.colmap.json` header→index map
derived from the actual header row (never hard-code column offsets — both
backends drift). `goget` has no flat all-fields exporter, so its pull is a
multi-table export (`plant_history` excluded by default — it's multi-GB); it
keeps soft-deleted records (GOGET deletes at the plant level; rows stay in
Postgres with `plant.deleted` set) and propagates the flag into every child CSV
as appended `plant_deleted` / `plant_deletedTimestamp` columns.

## Setup

Postgres trackers (`lng`, `gogpt`, `goget`):

```bash
pip install -r requirements.txt
export GEM_READONLY_DB_URL='postgres://readonly:PASSWORD@HOST:5432/DBNAME'
```

(A gitignored `.env` works too if your shell loads it — never commit
credentials.)

Sheets trackers (`ggit`, `goit`) need no pip packages, but do need the **`gws`
CLI** (Google Workspace CLI) authenticated against the work profile:

```bash
gws --version                        # brew install if missing
ls ~/.config/gws-gem                 # read-only work profile, must exist
```

Reads use `GOOGLE_WORKSPACE_CLI_CONFIG_DIR=~/.config/gws-gem` with the file
keyring backend; override the profile with `GEM_SHEETS_GWS_CONFIG_DIR` if
needed. `gem_sheets.py` refuses a write-scoped profile. If auth has expired,
re-run the login interactively — it needs a browser.

**Authenticated access only.** Anonymous/public Google export URLs (gviz
`tqx=out:csv`, `/export?format=csv`, `/pub`, `/htmlview`) 401 by design since
2026-07-29 and must never be reintroduced here or in any consumer. There is
also no CI credential: the `gem-analysis` service account was deleted
2026-07-31, so Sheets pulls are laptop-only, run by hand.

## Shared code (repo root)

- `gem_query.py` — the Postgres engine: read-only connection
  (`build_engine()`), schema introspection, single-table / multi-table
  (FK-traversal) exports, and the `--all-fields {lng,gogpt}` dispatch. Works
  for ANY project type (`--project-type lng|combustion|goget|steel|...`).
  Consumers that need their own SQL should borrow `build_engine()` rather than
  calling `create_engine`/`psycopg2.connect` — it is what sets
  `default_transaction_read_only=on` and a statement timeout on every session.
- `gem_all_fields.py` — library reproducing the website's flat "Export all
  fields" CSVs from Postgres (LNG: 115 cols; GOGPT: 86 cols). **Running it
  directly is a no-op** — it's imported by `gem_query.py --all-fields` and the
  per-tracker `pull.py` scripts. Validation notes: `docs/ALL_FIELDS_STATUS.md`.
  No GOGET exporter yet — port one here following the lng/gogpt pattern if
  needed.
- `gem_sheets.py` — the Sheets engine: `gws`-based read-only access, the
  pipelines-sheet key, and the tab registry (`ggit`, `goit`,
  `pipeline_owners`, `hydrogen`) with each tab's header-row offset. CLI:
  `python gem_sheets.py --list-tabs`, `--tab ggit -o out.csv`, plus
  `--sheet-key` for any other spreadsheet.
- `gem_colmap.py` — the one implementation of column-map derivation, and the
  canonical expected-column maps for every tracker
  (`LNG_EXPECTED_COLUMNS`, `GOGPT_EXPECTED_COLUMNS`, `GGIT_…`, `GOIT_…`,
  `PIPELINE_OWNERS_…`). **Add newly-appearing GEM columns here**, not in a
  consumer repo — the researcher repos alias these maps. CLI:
  `python gem_colmap.py <csv> --tracker ggit`.
- `gem_pipeline_pull.py` — shared implementation behind `ggit/pull.py` and
  `goit/pull.py`.
- `gem_export_via_web.py` — cookie-based downloads of the website's own export
  endpoints. **NOT IN USE** — nothing invokes it; kept for reference only. Do
  not wire it back into any pull path without asking.
- `schema_dbml.py` — dumps the live schema as DBML to `docs/gem_schema.dbml`;
  paste into https://dbdiagram.io/d for an up-to-date relational diagram.

## Notes

- Everything here is **read-only** against both backends: the Postgres role is
  `readonly` and sessions additionally set `default_transaction_read_only=on`;
  Sheets access uses the read-only `gws` profile. The only sanctioned write
  path to the pipelines Sheet lives in
  `../goit-ggit-data-ops/route-lengths/` — never add a write here.
- Pulled CSVs and colmaps are gitignored — this repo versions the tooling,
  not data snapshots.
- `archive/` (gitignored) holds pre-restructure May-2026 export snapshots;
  delete it whenever.
- Consumers and their one canonical command each: `docs/CONSUMERS.md`.
