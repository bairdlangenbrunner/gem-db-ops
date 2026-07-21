#!/usr/bin/env python3
"""
schema_dbml.py — Dump the live GEM read-only Postgres schema as DBML.

Paste the output into https://dbdiagram.io/d (New Diagram → paste) to view an
up-to-date relational diagram — same tool as the shared 2026-05-11 schema
diagram, but generated from the database itself, so it's never stale.

Emits every public table with columns (type, pk, not null), all foreign keys
as Ref: lines, and TableGroup blocks by domain. Django/auth plumbing tables
(auth_*, django_*, account_*, socialaccount_*, user_settings) are excluded by
default; --include-system adds them.

Usage:
    python schema_dbml.py                     # -> docs/gem_schema.dbml
    python schema_dbml.py -o my.dbml
    python schema_dbml.py --include-system
"""
import argparse
import datetime
import sys
from pathlib import Path

from sqlalchemy import text

from gem_query import get_database_url, build_engine, DEFAULT_STATEMENT_TIMEOUT_MS

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "docs" / "gem_schema.dbml"

SYSTEM_PREFIXES = ("auth_", "django_", "account_", "socialaccount_")
SYSTEM_TABLES = {"user_settings"}

# Domain groupings for dbdiagram TableGroup blocks. Tables not listed land in
# "other" (a new table showing up there is the cue to re-home it here).
GROUPS = {
    "core_project": [
        "plant", "powerplant_unit", "status_timeline", "operator",
        "plant_owner", "plant_language", "plant_external_id",
        "unit_external_id", "project_geospatial", "project_links",
        "project_update", "unit_update", "project_country_subdivision",
        "thread", "comment", "plant_history",
    ],
    "entity_company": [
        "company", "company_owner", "entity_history", "entity_org_id",
        "entity_status", "entity_tag", "entity_type", "entity_update",
        "org_id", "ultimate_parent_rationale", "legal_entity_type",
    ],
    "lng": ["lng_project", "lng_unit"],
    "goget": ["goget_project", "reserves_production", "reserve_type"],
    "steel_iron": [
        "steel_project", "steel_unit", "steel_product",
        "steel_yearly_production", "iron_yearly_production",
        "relining_details", "relining_cost_unit",
    ],
    "power_combustion": [
        "unit_fuel", "unit_turbine", "turbine_manufacturer", "fuel_category",
        "fuel_detail", "technology", "technology_fuel_category",
        "capacity_rating", "chp", "ccs", "captive_industry_type",
        "captive_industry_use", "captive_non_industry_use",
        "hydrogen_capable", "hydrogen_generating", "hydrogen_greenwashing",
        "nuclear_model", "installation_type", "unit_replacement",
        "unit_replacement_type",
    ],
    "reference": [
        "country", "country_subdivision", "language", "status",
        "data_source", "external_id_system", "project_type",
        "quantity_unit", "research_status", "project_link_types",
    ],
    "datahub": ["datahub_release", "datahub_releasefile", "datahub_tracker"],
}


def is_system(table: str) -> bool:
    return table.startswith(SYSTEM_PREFIXES) or table in SYSTEM_TABLES


def fetch_schema(engine, include_system: bool):
    with engine.connect() as c:
        tables = [r[0] for r in c.execute(text(
            "select table_name from information_schema.tables "
            "where table_schema='public' and table_type='BASE TABLE' "
            "order by table_name"))]
        if not include_system:
            tables = [t for t in tables if not is_system(t)]
        tset = set(tables)

        cols = {}
        for t, name, typ, nullable in c.execute(text(
                "select table_name, column_name, udt_name, is_nullable "
                "from information_schema.columns where table_schema='public' "
                "order by table_name, ordinal_position")):
            if t in tset:
                cols.setdefault(t, []).append((name, typ, nullable == "YES"))

        pks = {}
        for t, col in c.execute(text("""
                select cl.relname, att.attname
                from pg_index i
                join pg_class cl on cl.oid = i.indrelid
                join pg_namespace ns on ns.oid = cl.relnamespace
                join pg_attribute att on att.attrelid = i.indrelid
                                     and att.attnum = any(i.indkey)
                where i.indisprimary and ns.nspname='public'""")):
            if t in tset:
                pks.setdefault(t, set()).add(col)

        fks = [r for r in c.execute(text("""
                select cl.relname, att.attname, tcl.relname, tatt.attname
                from pg_constraint con
                join pg_class cl on cl.oid = con.conrelid
                join pg_namespace ns on ns.oid = cl.relnamespace
                join pg_class tcl on tcl.oid = con.confrelid
                join pg_attribute att on att.attrelid = con.conrelid
                                     and att.attnum = any(con.conkey)
                join pg_attribute tatt on tatt.attrelid = con.confrelid
                                      and tatt.attnum = any(con.confkey)
                where con.contype='f' and ns.nspname='public'
                  and array_length(con.conkey,1)=1
                  and array_length(con.confkey,1)=1
                order by cl.relname, att.attname"""))
               if r[0] in tset and r[2] in tset]
    return tables, cols, pks, fks


def emit_dbml(tables, cols, pks, fks) -> str:
    stamp = datetime.date.today().isoformat()
    out = [f"// GEM relational database schema — generated {stamp} from the "
           "live read-only Postgres by schema_dbml.py.",
           f"// {len(tables)} tables, {len(fks)} foreign keys. "
           "Paste into https://dbdiagram.io/d to view.", ""]
    for t in tables:
        out.append(f"Table {t} {{")
        for name, typ, nullable in cols.get(t, []):
            attrs = []
            if name in pks.get(t, ()):
                attrs.append("pk")
            elif not nullable:
                attrs.append("not null")
            suffix = f" [{', '.join(attrs)}]" if attrs else ""
            ident = f'"{name}"' if any(ch.isupper() for ch in name) else name
            out.append(f"  {ident} {typ}{suffix}")
        out.append("}")
        out.append("")

    grouped = set()
    for gname, members in GROUPS.items():
        present = [t for t in members if t in tables]
        grouped.update(present)
        if present:
            out.append(f"TableGroup {gname} {{")
            out.extend(f"  {t}" for t in present)
            out.append("}")
            out.append("")
    leftover = [t for t in tables if t not in grouped]
    if leftover:
        out.append("TableGroup other {")
        out.extend(f"  {t}" for t in leftover)
        out.append("}")
        out.append("")

    def q(table, col):
        c = f'"{col}"' if any(ch.isupper() for ch in col) else col
        return f"{table}.{c}"

    for src_t, src_c, tgt_t, tgt_c in fks:
        out.append(f"Ref: {q(src_t, src_c)} > {q(tgt_t, tgt_c)}")
    out.append("")
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    p.add_argument("--include-system", action="store_true",
                   help="Include Django/auth plumbing tables")
    args = p.parse_args()

    engine = build_engine(get_database_url(), DEFAULT_STATEMENT_TIMEOUT_MS)
    tables, cols, pks, fks = fetch_schema(engine, args.include_system)
    dbml = emit_dbml(tables, cols, pks, fks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(dbml)
    print(f"wrote {args.output} ({len(tables)} tables, {len(fks)} refs)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
