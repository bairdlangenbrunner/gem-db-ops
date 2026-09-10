# gem-db-ops

The single home of GEM data pulls, across two backends: the read-only Postgres
project database (`GEM_READONLY_DB_URL`) and the pipelines Google Sheet (via the
`gws` CLI, read-only profile `~/.config/gws-gem`). `README.md` has the full
layout and setup; `docs/CONSUMERS.md` maps each consumer repo to its one
canonical command. The short version:

Postgres pulls:

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

Sheets pulls (the pipeline trackers are NOT in Postgres — no pipeline
`projectType` exists there):

- "pull GGIT" / "pull the gas pipelines" → `python ggit/pull.py` →
  `ggit/gem_export_ggit.csv` + colmap. GGIT's **LNG terminals** are a
  different pull (`lng/pull.py`, Postgres) — ask which if it's ambiguous.
- "pull GOIT" → `python goit/pull.py` → `goit/gem_export_goit.csv` + colmap.
- Either pull takes `--with-owners` for the pipeline operators/owners tab, and
  `--map-only` to re-derive a colmap without re-pulling. Header rows are not
  row 0 (gas 2, oil/NGL 2, owners 1) — `gem_sheets.py`'s tab registry owns
  those offsets; don't hard-code them elsewhere.

Rules:

- **Never write to either backend.** Everything here is read-only exports: the
  Postgres role is `readonly` (+ `default_transaction_read_only=on`) and the
  `gws` profile is read-scoped (`gem_sheets.py` refuses a write profile). The
  one sanctioned write path to the pipelines Sheet is
  `../goit-ggit-data-ops/route-lengths/` — don't add a write here.
- **Never use anonymous/public Google export URLs** (gviz `tqx=out:csv`,
  `/export?format=csv`, `/pub`, `/htmlview`) — they 401 by design since
  2026-07-29. Authenticated `gws` reads only. Sheets pulls are laptop-only:
  there is no CI credential (the `gem-analysis` service account was deleted
  2026-07-31).
- **Never commit credentials or pulled CSVs** (both gitignored).
- **`gem_export_via_web.py` is NOT in use** — the cookie-based website export
  path is disconnected everywhere (kept for reference only). Do not invoke it
  or wire it back into a pull path without asking the user.
- After a pull, sanity-check the CSV actually refreshed (mtime + row count)
  and report the row/column counts.
- `gem_all_fields.py` run directly is a silent no-op — always pull via a
  `pull.py` or `gem_query.py --all-fields`.
- **One implementation each, here.** `gem_query.build_engine()` is the only
  Postgres connection, `gem_sheets.py` the only Sheets client, `gem_colmap.py`
  the only column-map derivation and the canonical home of every tracker's
  expected-column map. New GEM columns get added to `gem_colmap.py`, not to a
  consumer repo. If a consumer needs custom SQL, it borrows `build_engine()`.
- This repo is the ONLY home of the pull engine (single source of truth as of
  2026-07-21, extended to the Sheets backend 2026-08-11). Consumers keep no
  copies — `../lng-terminals-researcher`, `../gogpt-researcher`,
  `../pipelines-researcher`, and `../goit-ggit-interim-maps` all call in — so an
  engine fix here fixes every consumer. When adding a capability, check whether
  a consumer already hand-rolled it and delete that copy.
