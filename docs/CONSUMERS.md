# Consumers — one canonical pull command each

Every repo that reads GEM data goes through this one. This file is the map:
which sibling repo consumes what, by which command, and what it is forbidden to
re-implement. Last swept **2026-08-11** (the sweep that moved the Sheets reader,
the Postgres engine borrow, and all column-map derivation in here).

**The rule:** no consumer keeps its own Postgres connection, Sheets client, or
expected-column map. If you are about to write `create_engine`,
`psycopg2.connect`, `pygsheets.authorize`, a `gws ... values get` invocation, or
a dict of GEM header strings in another repo — stop; call into gem-db-ops
instead, and extend it if something is missing.

Layout assumption everywhere: gem-db-ops sits beside its consumers in
`_github-repos-gem/`. Override with `GEM_DB_OPS_REPO=/path/to/gem-db-ops`.

## lng-terminals-researcher (LNG terminals, Postgres)

| What | How |
|---|---|
| Fresh export | `python ../../gem-db-ops/lng/pull.py --output scripts/gem_export.csv` (from `scripts/`), or `python ../../gem-db-ops/gem_query.py --all-fields lng -o gem_export.csv` |
| Column map | `scripts/pull_gem_db.py --map-only` — derivation only; `EXPECTED_COLUMNS` is an alias of `gem_colmap.LNG_EXPECTED_COLUMNS` |
| Ad-hoc SQL | `scripts/paths.py` → `get_engine()`, which borrows `gem_query.build_engine()` (used by `captive_power_colocation.py`, `location_edit_provenance.py`, `refsweep_missing_year.py`, `fetch_timeline.py`, `entity_lookup.py`) |

Must not re-add: an engine builder, `psycopg2` usage, or the 115-column map.
New LNG columns go in `gem_colmap.LNG_EXPECTED_COLUMNS` (its `TODO.md` points
there for the open `AltFuelNotes` question).

## gogpt-researcher (oil & gas power plants, Postgres)

| What | How |
|---|---|
| Fresh export | `python ../../gem-db-ops/gogpt/pull.py --output gem_export_gogpt.csv` (from `scripts/`) |
| Column map | `python pull_gem_db.py --map-only` — alias of `gem_colmap.GOGPT_EXPECTED_COLUMNS`; keeps only the repo-specific `READ_ONLY_COMPUTED` / `READ_ONLY_OUT_OF_SCOPE` derivations |
| Then | `python scope_filter.py` — the export is every combustion unit (oil+gas+coal+bio), so the GOGPT-only view is derived locally on purpose. Keep the unfiltered CSV for coal-conversion cross-checks. |
| Sibling paths | `scripts/paths.py` → `db_ops_repo()` |

Must not re-add: the 86-column map (add new columns in `gem_colmap.py`, and
`COMPUTED_COLUMNS`/`OUT_OF_SCOPE_COLUMNS` in its own `schema_constants.py` in
the same pass).

## pipelines-researcher (GGIT gas + GOIT oil/NGL, Sheets)

| What | How |
|---|---|
| Dated snapshots | `./scripts/refresh_csvs.sh` (`--working` for gitignored working copies) — a thin wrapper over `ggit/pull.py` and `goit/pull.py --with-owners` |
| Direct pull | `python ../gem-db-ops/goit/pull.py --output data/oil.csv --with-owners` |
| Column map | written beside each CSV by the pull; re-derive with `python ../gem-db-ops/gem_colmap.py <csv> --tracker goit` |
| Facility gazetteer | `scripts/refresh_facility_gazetteer.py` reads gem-db-ops' own `goget/gem_export_goget_tables/` and `gogpt/gem_export_gogpt.csv` snapshots in place (path via `paths.db_ops_repo()`) — refresh them with `goget/pull.py` / `gogpt/pull.py` first |
| Sibling paths | `scripts/paths.py` → `db_ops_repo()` |

Must not re-add: `scripts/_sheets_pull.py` (deleted 2026-08-11 — it became
`gem_sheets.py`), tab titles/gids, header-row offsets, or any anonymous export
URL.

## goit-ggit-interim-maps (map data builders, Postgres)

| What | How |
|---|---|
| Connection | `scripts/gem_db.py` → `build_readonly_engine()` / `fetch_all(query)`, borrowed from `gem_query.build_engine()` |
| Users | `scripts/build_lng_map_data.py`, `scripts/build_goget_areas.py` |

Must not re-add: the `psycopg2.connect` those two builders used before
2026-08-11. Extend `scripts/gem_db.py` if a new query needs something.

## goit-ggit-data-ops (release production)

Reads should come from `ggit/pull.py` / `goit/pull.py` (+ `--with-owners`) and
the Postgres pulls; for a summary tab in some other spreadsheet use
`python ../gem-db-ops/gem_sheets.py --sheet-key <key> --tab '<title>' -o out.csv`.
Its notebooks still carry dead `pygsheets.authorize(...)` calls (the
`gem-analysis` service account was deleted 2026-07-31) — repoint one at
gem-db-ops when you next touch it rather than doing a blanket rewrite.

**This is the read/write boundary.** `goit-ggit-data-ops/route-lengths/`
(`sheets_client.py` + `sheet_writer.py`, `gws-gem-write`, per-edit approval) is
the ONLY sanctioned write path to the pipelines Sheet, and it stays there.
gem-db-ops never writes.

## gem-desk (email/analysis workspace)

One-off analysis scripts pull fresh with `python ../gem-db-ops/lng/pull.py` or
`gem_query.py --all-fields lng -o …` and compute locally
(`emails/anna-lng-glut/`, `emails/sam-hall-japanese-lng-ownership/`,
`writing-and-analysis/lng-industry-africa-piece/03-gem-data/`). `docs/repos.md`
is the ecosystem map. Historical findings files name the path the pull used *at
the time* — leave that provenance intact.

Non-pipeline work sheets go through `gem_sheets.read_tab_values(title,
sheet_key=…)`: `research-cycles/ggit-2026-pipelines-update/possible-updates/build_possible_updates_triage.py`
reads its two tabs live that way (it used to need two hand-run `gws sheets +read`
commands and two JSON dumps on disk — both gone; replayed byte-identical against
the 2026-07-29 output).

## Dead ends (don't revive in place)

- `ggit-dashboard/` and `goit-dashboard/` (top-level repos) — prototypes whose
  `app.py` was copied into `goit-ggit-data-ops/dashboards/`; both authenticate
  with the deleted `gem-analysis` service account. Each now carries a README
  saying so.
- `gem_export_via_web.py` in this repo — the cookie-based website export path.
  Nothing invokes it; don't wire it back in without asking.
- `GlobalEnergyMonitor/maps` and `GlobalEnergyMonitor/testing-maps` (both
  **public**) — their `helper_functions.py` hard-coded a project-database
  connection string feeding a dead `pull_from_db_sql()` (`create_engine` was
  never even imported). Removed from both 2026-08-14; the string was a
  decommissioned instance, not the live one. It survives in git history, so
  **never** put a connection string in a public map repo again: if those repos
  ever need database reads, they call in here and take the URL from
  `GEM_READONLY_DB_URL`. A credential-free `pull_from_db_sql()` stub still sits
  in `maps/_scripting/helper_functions.py` on the default branch — it references
  an undefined `DATABASE_URL`, so it cannot run; delete it rather than "fixing"
  it with a literal.
