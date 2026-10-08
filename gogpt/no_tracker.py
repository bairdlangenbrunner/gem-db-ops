#!/usr/bin/env python3
"""
List the combustion units the GEM database has not assigned to any tracker:
the web UI's "No tracker found" choice in the combustion tracker search.

A combustion unit (plant.projectType = 1) gets powerplant_unit.trackerSearch
set to GOGPT, GCPT or GBPT from its primary fuel. A unit with no fuel, or with
several fuels and no primary one, gets no value and drops out of every
tracker's export and worklist. The GOGPT QC/Country checklist asks the
researcher to review these ("no tracker found" units, end-of-update block),
so this lists them per country or state. Deleted units and units of deleted
plants are left out unless --include-deleted is given; the web UI hides them.

Requires:
    export GEM_READONLY_DB_URL='postgres://readonly:PASSWORD@HOST:5432/DBNAME'

Usage (from gogpt/):
    python no_tracker.py                                  # every country, CSV + summary
    python no_tracker.py --country "United States" --state Indiana
    python no_tracker.py --country Germany --json          # JSON to stdout instead of CSV
    python no_tracker.py --include-deleted                 # add deleted unit rows

Default CSV: gogpt/no_tracker.csv (gitignored like every pulled CSV).
Status comes from milestone_timeline (the step marked current, else the last
step), never from the legacy powerplant_unit.status_id (CLAUDE.md).
Checked 2026-10-07: 45 units, 6 of them live, none live in the United States.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

COMBUSTION_PROJECT_TYPE = 1
DEFAULT_OUT = HERE / "no_tracker.csv"
COLUMNS = ["unit_id", "plant_id", "plant", "unit", "country", "state", "unit_fuels",
           "plant_fuels", "capacity_mw", "status", "unit_deleted", "plant_deleted",
           "likely_reason"]

SQL = """
select 'G' || u.id as unit_id, 'L' || p.id as plant_id, p.name as plant, u.name as unit,
       c."gemName" as country, p.subnational as state,
       u."fuelCategorySearch" as unit_fuel_ids, p."fuelCategorySearch" as plant_fuel_ids,
       u.capacity as capacity_mw,
       (select m.status from milestone_timeline m where m.unit_id = u.id
         order by m."makeCurrent" desc nulls last, m."order" desc, m.id desc limit 1) as status,
       coalesce(u.deleted, false) as unit_deleted, coalesce(p.deleted, false) as plant_deleted
from powerplant_unit u
join plant p on p.id = u.plant_id
join country c on c.id = any(p."countrySearch")
where p."projectType" = :ptype and u."trackerSearch" is null
"""


def likely_reason(unit_fuel_ids):
    n = len(unit_fuel_ids or [])
    if n == 0:
        return "no fuel on the unit"
    if n > 1:
        return "several fuels and no primary fuel"
    return "one fuel but no tracker assigned; ask the database team"


def fetch_no_tracker(engine, country=None, state=None, include_deleted=False):
    """Rows (dicts, COLUMNS keys) for combustion units with no tracker value."""
    from sqlalchemy import text

    sql, params = SQL, {"ptype": COMBUSTION_PROJECT_TYPE}
    if not include_deleted:
        sql += " and not coalesce(u.deleted, false) and not coalesce(p.deleted, false)"
    if country:
        sql += ' and c."gemName" ilike :country'
        params["country"] = country
    if state:
        sql += " and p.subnational ilike :state"
        params["state"] = state
    sql += " order by c.\"gemName\", p.subnational, p.name, u.name"
    with engine.connect() as cx:
        fuels = dict(cx.execute(text("select id, name from fuel_category")).fetchall())
        rows = cx.execute(text(sql), params).mappings().all()
    out, seen = [], set()
    for r in rows:
        d = dict(r)
        if d["unit_id"] in seen:      # a plant in several countries joins once per country
            continue
        seen.add(d["unit_id"])
        uf, pf = d.pop("unit_fuel_ids") or [], d.pop("plant_fuel_ids") or []
        d["unit_fuels"] = "; ".join(fuels.get(i, str(i)) for i in uf)
        d["plant_fuels"] = "; ".join(fuels.get(i, str(i)) for i in pf)
        d["capacity_mw"] = float(d["capacity_mw"]) if d["capacity_mw"] is not None else None
        d["state"] = d["state"] or ""
        d["likely_reason"] = likely_reason(uf)
        out.append({k: d.get(k) for k in COLUMNS})
    return out


def summary(rows, country=None, state=None):
    where = f" in {state}, {country}" if state else (f" in {country}" if country else "")
    if not rows:
        return f"No combustion units without a tracker{where}."
    live = sum(1 for r in rows if not r["unit_deleted"] and not r["plant_deleted"])
    lines = [f"{len(rows)} combustion unit(s) without a tracker{where}, {live} live."]
    for r in rows:
        flag = "" if (not r["unit_deleted"] and not r["plant_deleted"]) else " (deleted)"
        cap = f"{r['capacity_mw']:g} MW" if r["capacity_mw"] is not None else "no capacity"
        place = ", ".join(x for x in (r["state"], r["country"]) if x)
        lines.append(f"  {r['unit_id']}  {r['plant']} unit {r['unit'] or '(no name)'}, {place}: "
                     f"{cap}, {r['status'] or 'no status'}; {r['likely_reason']}{flag}")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--country", help="GEM country name, e.g. 'United States'")
    p.add_argument("--state", help="State or province (plant.subnational), e.g. Indiana")
    p.add_argument("--include-deleted", action="store_true",
                   help="Also list deleted units and units of deleted plants")
    p.add_argument("--output", "--out", dest="out", type=Path, default=DEFAULT_OUT,
                   help=f"CSV path (default {DEFAULT_OUT.name})")
    p.add_argument("--json", action="store_true", help="Print JSON to stdout, write no CSV")
    args = p.parse_args()

    from gem_query import get_database_url, build_engine, DEFAULT_STATEMENT_TIMEOUT_MS
    engine = build_engine(get_database_url(), DEFAULT_STATEMENT_TIMEOUT_MS)
    rows = fetch_no_tracker(engine, args.country, args.state, args.include_deleted)

    if args.json:
        json.dump(rows, sys.stdout, indent=1)
        print()
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            w.writeheader()
            w.writerows(rows)
        print(f"  wrote {len(rows)} row(s) to {args.out}", file=sys.stderr)
    print(summary(rows, args.country, args.state), file=sys.stderr)


if __name__ == "__main__":
    main()
