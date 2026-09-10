# GEM "All Fields" LNG + GOGPT Export — Progress Notes

> **Restructure notes.** 2026-07-21: the repo has per-tracker pull folders
> (`lng/`, `gogpt/`, `goget/`, each with a `pull.py`); the scripts described
> below still live at the repo root, and the loose CSV snapshots this file
> references were moved to `archive/` (gitignored). 2026-08-11: the Sheets
> backend was added (`ggit/`, `goit/`, `gem_sheets.py`) — irrelevant to this
> file, which is Postgres-only — and column-map derivation plus the canonical
> `LNG_EXPECTED_COLUMNS` / `GOGPT_EXPECTED_COLUMNS` moved into `gem_colmap.py`,
> so a column added to `LNG_COLUMNS`/`GOGPT_COLUMNS` here must be added there
> too. See `README.md` and `docs/CONSUMERS.md`.

Working file for the `gem_query.py --all-fields {lng,gogpt}` mode that reproduces
the website's denormalized "Export all fields" CSVs.

Last touched: 2026-05-22.

## TL;DR

- `python gem_query.py --all-fields lng   -o terminals.csv` — 115-col LNG CSV
  (one row per `lng_unit`).
- `python gem_query.py --all-fields gogpt -o gogpt.csv` — 86-col GOGPT CSV
  (one row per combustion-projectType `powerplant_unit`).
- CLI flag accepts `lng` or `gogpt`; passing neither is an error.

Validated against fresh website exports:

| Export | Reference file | Rows | Cell match | Byte-identical rows |
|---|---|---:|---:|---:|
| LNG   | `all-fields-2026-05-22T181922.csv`    | 1,261 | 96.46% | 8.01% |
| GOGPT | `GOGPT-all-2026-05-22T183522.csv`     | 34,515 | 99.29% | 65.21% |

Implementation in `gem_all_fields.py`; `gem_query.py` adds the `--all-fields`
CLI choice and dispatches to `export_all_fields` (LNG) or
`export_gogpt_all_fields` (GOGPT). Many format helpers are shared between the
two exporters.

> **Note on the "GOGPT" filter:** the website's URL `?format=gas_all&tracker=GOGPT`
> is misleading — the export actually contains *every* combustion-projectType
> unit (oil + gas + coal + bioenergy), not just `trackerSearch='GOGPT'` ones.
> Our exporter does the same.

## Files in this project

| File | What it is |
|---|---|
| `gem_query.py` | Original query / single-table / multi-table exporter. `--all-fields` mode added near `main()`. |
| `gem_all_fields.py` | Everything for the all-fields mode: SQL queries, formatters, column derivation, recursive parent traversal, row builder. |
| `ALL_FIELDS_STATUS.md` | This file. |
| `.claude/settings.local.json` | Set to `bypassPermissions` mode so the harness stops asking for confirmation on every command. |

## How to run

```bash
# Requires GEM_READONLY_DB_URL in env.
export GEM_READONLY_DB_URL='postgres://readonly:PASSWORD@HOST:5432/DB'

# LNG export (~1,260 rows, ~5 sec):
python gem_query.py --all-fields lng -o terminals.csv

# GOGPT / oil & gas / combustion export (~34,500 rows, ~25 sec):
python gem_query.py --all-fields gogpt -o gogpt.csv

# Small sample for iterating (plant limit, not unit limit):
python gem_query.py --all-fields lng --limit 30 -o /tmp/lng.csv
```

## Accuracy snapshot

Compared against `all-fields-2026-08-28T161944.csv` (the 2026-05-22 download it
was previously measured against gave 96.46% / 7.93%):

```
1281 our rows, 1281 ref rows, 1281 matched by (TerminalID, UnitID)
97.83% cell match (3,144 / 144,753 cells differ)
17.64% rows are exact byte-for-byte matches (226 / 1,281)
```

All six **cost value** columns — `Cost`, `CostUnits`, `CostYear`, `CostUSD`,
`CostEuro`, `TotKnownTerminalCostsUSD` — now reproduce byte-for-byte.

Top diff columns (out of 115) and their root causes:

| Column | % differ | Cause | Status |
|---|---:|---|---|
| `Capacity [ref]` | 71% | DB has `powerplant_unit.capacityDatasource` for most units; the website hides it when redundant with a project-level source. Gating rule unknown. | Open |
| `CostEuro` | 0% | Fixed FX table `CURRENCY_TO_EUR` (year-independent), quantized to 2dp. | Exact |
| `Cost [ref]` | 10% | Unit source when the unit carries a cost, else the project source. 129 rows whose unit cost *and* source are both populated print nothing on the website, and nothing in the replica separates them from the 333 identical rows that do. | Open |
| `StartDate [ref]` | 30% | Currently unions datasources of every `status_timeline` row with `status='operating'`. Order/dedup logic differs from website in some cases. | Open |
| `TotKnownTerminalCostsUSD` | 0% | `lng_project.cost` where present (a whole-terminal figure that *overrides*, not merely backfills), else the sum of the non-deleted units' converted costs. | Exact |
| `State/Province` | 25% | Priority chain: `unit.subnational > plant.subnational > plant.subnationalLookup → country_subdivision.name`. Some rows use website-only locale strings. | Open |
| `Parent` / `Parent GEM Entity ID` | 18% | Reads `company.gemParents` / `gemParentsIds` from the direct owners. Self-reference fallback handled. Remaining diffs are edge cases in share normalization or multi-owner concatenation. | Mostly done |
| `CostUSD` | 0% | Fixed FX table `CURRENCY_TO_USD`, plus the project-level cost on single-unit terminals. | Exact |
| `Owner` | 17% | Ordered by `plant_owner.id` ascending; website appears to use a different sort that isn't share/name/id-based. | Open |

The complete dump of diff counts is reproducible by running the diff script in
the "Useful one-liners" section below.

## What's implemented

The website exports 115 columns. Coverage:

**Fully working**:
- IDs and name fields (TerminalID with T-prefix, UnitID with G-prefix, Parent GEM
  Entity ID with E-prefix, Wiki, TerminalName, UnitName)
- FacilityType, Fuel, OtherNames, LocalNames, Language
- Country/Area, Region, SubRegion (via country table joins)
- Researcher, LastUpdated (from latest `unit_update` row + `auth_user`)
- Owner aggregation (`company.name + " " + legal_entity_type.type` with share)
- Operator (just `company.name`, no legal_type suffix — verified vs website)
- VesselOperator / VesselOwner (split by `operator.type`)
- Capacity (raw, mtpa, Bcm/y, plant-level Tot* sums by facility_type)
- Latitude / Longitude / Accuracy / Location (read from cached `plantJSON` /
  `unitJSON` snapshots so precision and trailing zeros match the website)
- Boolean columns (Offshore, Floating, Opposition, CCS, LH2, NH3, etc.)
- Status timeline → ProposalYear, ConstructionYear, OriginalPlannedStartYear,
  LatestPlannedStartYear, ActualStartYear/2/3, ShelvedYear, CancelledYear,
  StopYear, PlannedStopYear, FIDStatus, FIDYear, and their `[ref]` siblings
- Datasource resolution (every `*Datasource` jsonb column → `data_source.url`,
  comma-joined in original order)
- ShelvedCancelledStatusType (collapses `inferred 4 y` → `inferred`)
- Parent traversal via `company.gemParents` / `gemParentsIds` (curated GEM
  field, not via `company_owner` which would pull in Vanguard/Blackrock-style
  public shareholders). Self-reference fallback when owner is its own parent.
- ParentHQCountry (extracts E-prefixed IDs from `gemParentsIds` and looks up
  `company.headquarters_country_id → country.gemName`)

**Partially working** — see diff table above.

**Not implemented**:
- `VesselParent` — would require running the company_owner traversal on vessel-owner companies
- `TotTerminalCost [ref]` — plant-level cost reference aggregate

## Key things learned while building this

These are the things I'd want to remember if picking this up later:

### Field-level mapping discoveries
1. The website renders most location and capacity fields from the **denormalized
   `plant.plantJSON` and `powerplant_unit.unitJSON` snapshots**, not the raw
   columns. The JSON values preserve the exact display string (e.g., trailing
   zeros on coordinates). Reading raw `plant.latitude` instead would give
   different precision.
2. **`company.gemParents` and `company.gemParentsIds`** are *curated* GEM-edited
   parent lists. They're separate from `company_owner` (which holds public
   shareholder data). The website's Parent column maps 1:1 to `gemParents`,
   not to a `company_owner` traversal.
3. **Owners and operators format names differently**: owners are
   `company.name + " " + legal_entity_type.type` (e.g. "INPEX Masela Ltd"),
   operators are just `company.name` ("INPEX Masela"). Verified against
   multiple rows.
4. **`operator.type` is a discriminator** — values `operator`, `vesselOperator`,
   `vesselOwner` split into different display columns. Note the **camelCase**:
   testing for `vessel_owner`/`vessel_operator` matches nothing and silently
   empties both columns. Unlike Owner/Operator, the vessel columns render bare
   company names — the website never appends the `[NN%]` share even where
   `operator.share` is populated.
5. **`plant.subnationalLookup_id` → `project_country_subdivision.name`** is the
   resolved ISO subdivision, but researchers often type a local-language
   variant into `plant.subnational` that the website prefers. The priority
   chain that works most reliably is `plant.subnational > unitJSON.subnational
   > plant.subnationalLookup`.
6. **The cost model has three levels, and the project level *overrides*.**
   `lng_unit.cost` is the per-unit figure; `lng_project.cost` is a whole-terminal
   figure. `TotKnownTerminalCostsUSD` is the project cost wherever one exists,
   and only otherwise the sum of the units' converted costs — Papua LNG carries a
   4.5bn AUD unit cost yet totals 18bn USD, its project value. For the per-row
   `Cost`/`CostUSD`, the project cost stands in only on **single-unit** terminals;
   pushing it onto each row of a multi-unit terminal would multiply it. And
   `Cost` itself is the **verbatim JSON string** (`unitJSON->>'cost'`, or
   `plantJSON->>'cost'` for the project fallback), so `1500000000`,
   `1500000000.00` and `2.67E+13` all survive as the editor typed them.
7. **FX is a fixed table, not a per-year one.** The implied rate for each
   `costUnit` is identical across every `CostYear` in the export, so no
   historical series is needed. There is no currency table anywhere in the
   read-only Postgres (72 tables checked), so `CURRENCY_TO_USD` /
   `CURRENCY_TO_EUR` in `gem_all_fields.py` are reproduced from a download.
   `CostEuro` has its **own** table — it is not `CostUSD / 1.09`; GBP is 1.156
   where the derivation would give 1.1559 — and is quantized to 2dp.
8. **Capacity conversions**: the website uses `bcm = mtpa / 0.735` (equivalent
   to factor 1.36054…), with ROUND_HALF_UP at 2 dp. Not the more common
   industry factor of 1.36 or the IGU value 1.379. For non-mtpa/bcm units, a
   small lookup table covers `bcf/d` (×7.67) and `MMcf/d` (×0.00767).
9. **Researcher / LastUpdated come from `unit_update`** (latest by `lastUpdated`),
   joined to `auth_user`. NOT from `project_update`, which is empty for most
   LNG plants.
8. **Share formatting differs by column**: Owner shares render as
   `[100%]` (no decimal when whole) or `[50.5%]` (one decimal). Parent shares
   always render as `[100.0%]` (one decimal even when whole). Implemented as
   `_fmt_share_owner` vs `_fmt_share_parent`.
9. **Status timeline → year column split** works as follows:
   - Current `Status` = highest-order row where substatus ≠ `planned`
     AND status ≠ `FID`. FID is a milestone, never the lifecycle status.
   - Operating rows split by substatus: `planned` → `OriginalPlannedStartYear`
     (first by order) / `LatestPlannedStartYear` (last). `actual` (or null) →
     `ActualStartYear/2/3` (chronological by order).
   - `StopYear` = `CancelledYear` if cancelled, else `ShelvedYear`.
   - `StartDate [ref]` unions the datasources of *all* operating-status rows.
10. **Datasource references**: every `*Datasource` jsonb column holds a list of
    integer `data_source.id` values. The website resolves each to
    `data_source.url`, comma-joins. Duplicates are preserved.

### Things that bit me along the way
- Coordinate precision is per-row and unrelated to column type — relying on
  raw numeric columns gives wrong trailing-zero behavior. Use the JSON
  snapshots.
- The `company_owner` graph has cycles (joint-venture cross-holdings). The
  recursive parent walk in `_trace_ultimate_parents` tracks visited nodes per
  path to break them. Even so, this approach was abandoned in favor of
  `gemParents` for the actual output — but the recursion code is still in the
  file in case it's needed later.
- The all-fields capacity column ordering in the website export had a UTF-8
  BOM on the first header — handled by writing with `encoding="utf-8-sig"`.
- Database modifications happen after exports — some rows differ because the
  reference CSV was generated before recent DB edits. Best example: Abadi's
  `Location` was "Nustual Island" in the export but "Lermatang Village" in
  the live DB on 2026-05-22.

## Where to pick up

### Quick wins (probably ≤ 1 hour each)
1. **Owner ordering**: try sorting by `plant_owner.modified` or by `company.id`
   to see if a non-obvious key matches the website. Currently sorts by
   `plant_owner.id` ascending.
2. **State/Province priority**: experiment with prioritizing
   `subnationalLookup → country_subdivision.name` for *some* countries and
   free-text for others. There may be a pattern by country.
3. **Status [ref]**: my current code emits the datasource of the *current*
   status row only. The website may emit multiple status datasources.

### Bigger projects
1. **Reverse-engineer the `[ref]` hide logic**: for `Capacity [ref]`,
   `Cost [ref]`, `Financing [ref]` — when does the website suppress an
   otherwise-populated value? The shared-URL guess was tested on `Cost [ref]`
   and **falsified** (the 129 suppressed rows split 77/52 on whether their URL
   also appears in another `[ref]` column, the 333 shown rows 144/189). Nothing
   in `lng_unit`, `plant`, `data_source` or the JSON snapshots separates the two
   groups, so the rule is probably not in the read-only replica at all.
2. **Owner-display sort order**: pull a larger sample and look for a hidden
   ordering signal (creation timestamp on `company`? a JSON-stored display
   order on `plant.plantJSON`?).

## Useful one-liners

Diff our output against the reference, aggregate counts per column:

```bash
python gem_query.py --all-fields -o /tmp/af.csv
python3 << 'EOF'
import csv
REF = "/Users/baird/Downloads/all-fields-2026-05-22T161115.csv"
OURS = "/tmp/af.csv"
with open(REF, encoding="utf-8-sig") as f: ref = {(r["TerminalID"], r["UnitID"]): r for r in csv.DictReader(f)}
with open(OURS, encoding="utf-8-sig") as f: ours = {(r["TerminalID"], r["UnitID"]): r for r in csv.DictReader(f)}
counts = {}
n = 0
for k in ours:
    if k not in ref: continue
    n += 1
    for col in ref[k]:
        if (ref[k][col] or "").strip() != (ours[k][col] or "").strip():
            counts[col] = counts.get(col, 0) + 1
for c, x in sorted(counts.items(), key=lambda kv: -kv[1])[:20]:
    print(f"{x:>4}/{n}  {c}")
EOF
```

Inspect a specific terminal's diffs:

```bash
python3 -c "
import csv
TID = 'T100000130274'  # Abadi
REF = '/Users/baird/Downloads/all-fields-2026-05-22T161115.csv'
OURS = '/tmp/af.csv'
def row(p):
    with open(p, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['TerminalID'] == TID: return r
ref, ours = row(REF), row(OURS)
for col in ref:
    r, o = (ref[col] or '').strip(), (ours[col] or '').strip()
    if r != o:
        print(f'[{col}]')
        print(f'  REF: {r[:120]!r}')
        print(f' OURS: {o[:120]!r}')"
```

Quick DB lookups (using gem_query.py's --sql mode):

```bash
# Get plantJSON for one terminal
python gem_query.py --sql 'SELECT "plantJSON" FROM plant WHERE id = 100000130274' -o /tmp/x.csv

# Status timeline for a unit
python gem_query.py --sql 'SELECT * FROM status_timeline WHERE unit_id = 100002027401 ORDER BY "order"' -o /tmp/x.csv

# Owner + parent info for a plant
python gem_query.py --sql 'SELECT po.share, c.name, c."gemParents", c."gemParentsIds" FROM plant_owner po JOIN company c ON c.id=po.company_id WHERE po.plant_id = 100000130274' -o /tmp/x.csv
```

## Architecture notes

`gem_all_fields.py` is structured as:

```
Constants & column list (lines 1-100)
Format helpers (lines 100-260)        _fmt_*, _join_*, _resolve_refs, _normalize_parent_shares
Capacity conversions (260-280)        CAPACITY_UNIT_TO_MTPA table
Bulk SQL fetchers (280-660)           _fetch_plants, _fetch_units, _fetch_owners, ...
Status-timeline derivation (660-800)  _derive_status_columns
Row composition (800-1090)            _build_row
Plant-level aggregates (1090-1130)    _compute_plant_totals (capacity + USD cost)
export_all_fields entry point (1130+) Runs all fetches, builds ctx, writes CSV
```

Strategy: do all the fetches up front (10-12 queries total, each batched
across all terminals), build dict-of-dicts lookups, then assemble rows in
Python. This is faster and simpler than a single mega-JOIN with string_agg.

The CLI wires in at `gem_query.py` — search for `args.all_fields` (line numbers
drift; don't cite one).
