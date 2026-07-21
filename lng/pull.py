#!/usr/bin/env python3
"""
Pull the current LNG terminals "all-fields" CSV from the GEM database and
derive the column-index map from the header row.

Primary path (no cookies): direct read-only Postgres via ../gem_query.py's
engine + ../gem_all_fields.py's exporter. Requires:

    export GEM_READONLY_DB_URL='postgres://readonly:PASSWORD@HOST:5432/DBNAME'

Fallback path (--via-web): cookie-based download from the project-DB website
via ../gem_export_via_web.py. Requires GEM_PROJECT_DB_SESSIONID and
GEM_PROJECT_DB_CSRFTOKEN (see that script's docstring for the cookie
extraction procedure).

Usage (from this folder or anywhere):
    python pull.py                      # fresh lng/gem_export.csv + .colmap.json
    python pull.py --output my.csv      # custom path
    python pull.py --map-only           # skip fetch; derive map from existing CSV
    python pull.py --via-web            # cookie-based website download instead
    python pull.py --limit 30           # small sample (plant limit, for testing)

Why re-derive the column map every pull: the all-fields export is ~115 columns
but the schema can drift between GEM database revisions (columns added,
renamed, reordered). Hard-coding offsets breaks silently; the derived map is
saved next to the CSV so downstream tooling reads the same one.
"""
import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

DEFAULT_OUT = HERE / "gem_export.csv"

# Columns downstream tooling depends on — keyed by canonical short name, value
# is the expected header text. The actual index is derived from the header row
# at runtime; a MISSING entry in the output means schema drift.
EXPECTED_COLUMNS = {
    "terminal_id": "TerminalID",
    "unit_id": "UnitID",
    "wiki": "Wiki",
    "terminal_name": "TerminalName",
    "unit_name": "UnitName",
    "facility_type": "FacilityType",
    "facility_type_ref": "FacilityType [ref]",
    "fuel": "Fuel",
    "status": "Status",
    "substatus": "Substatus",
    "status_ref": "Status [ref]",
    "country": "Country/Area",
    "researcher": "Researcher",
    "last_updated": "LastUpdated",
    "researcher_notes_unit": "ResearcherNotesUnit",
    "researcher_notes_project": "ResearcherNotesProject",
    "other_names": "OtherNames",
    "local_names": "LocalNames",
    "language": "Language",
    "owner": "Owner",
    "owner_ref": "Owner [ref]",
    "parent": "Parent",
    "parent_hq_country": "ParentHQCountry",
    "parent_entity_id": "Parent GEM Entity ID",
    "operator": "Operator",
    "operator_ref": "Operator [ref]",
    "capacity": "Capacity",
    "capacity_units": "CapacityUnits",
    "capacity_mtpa": "CapacityinMtpa",
    "capacity_bcm": "CapacityinBcm/y",
    "capacity_ref": "Capacity [ref]",
    "tot_import_mtpa": "TotImportLNGTerminalCapacityinMtpa",
    "tot_import_bcm": "TotImportLNGTerminalCapacityinBcm/y",
    "tot_export_mtpa": "TotExportLNGTerminalCapacityinMtpa",
    "tot_export_bcm": "TotExportLNGTerminalCapacityinBcm/y",
    "proposal_year": "ProposalYear",
    "proposal_month": "ProposalMonth",
    "proposal_date_ref": "ProposalDate [ref]",
    "construction_year": "ConstructionYear",
    "construction_month": "ConstructionMonth",
    "construction_date_ref": "ConstructionDate [ref]",
    "original_planned_start": "OriginalPlannedStartYear",
    "latest_planned_start": "LatestPlannedStartYear",
    "actual_start_year": "ActualStartYear",
    "actual_start_month": "ActualStartMonth",
    "actual_start_year_2": "ActualStartYear2",
    "actual_start_year_3": "ActualStartYear3",
    "start_date_ref": "StartDate [ref]",
    "shelved_year": "ShelvedYear",
    "shelved_year_ref": "ShelvedYear [ref]",
    "cancelled_year": "CancelledYear",
    "cancelled_year_ref": "CancelledYear [ref]",
    "stop_year": "StopYear",
    "stop_year_ref": "StopYear [ref]",
    "planned_stop_year": "PlannedStopYear",
    "shelved_cancelled_status_type": "ShelvedCancelledStatusType",
    "temp_facility": "TempFacility",
    "import_export_only": "ImportExportOnly",
    "location": "Location",
    "region": "Region",
    "sub_region": "SubRegion",
    "prefecture_district": "Prefecture/District",
    "state_province": "State/Province",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "accuracy": "Accuracy",
    "location_ref": "Location [ref]",
    "associated_terminals": "AssociatedTerminals",
    "associated_terminals_ref": "AssociatedTerminals [ref]",
    "source": "Source",
    "source_ref": "Source [ref]",
    "power_plants_supplied": "PowerPlantsSupplied",
    "power_plants_supplied_ref": "PowerPlantsSupplied [ref]",
    "captive_gas_power": "CaptiveGasPower",
    "captive_gas_power_ref": "CaptiveGasPower [ref]",
    "pipelines": "Pipelines",
    "pipelines_ref": "Pipelines [ref]",
    "cost": "Cost",
    "cost_units": "CostUnits",
    "cost_year": "CostYear",
    "cost_usd": "CostUSD",
    "cost_euro": "CostEuro",
    "cost_ref": "Cost [ref]",
    "tot_known_terminal_costs_usd": "TotKnownTerminalCostsUSD",
    "tot_terminal_cost_ref": "TotTerminalCost [ref]",
    "fid_status": "FIDStatus",
    "fid_year": "FIDYear",
    "fid_year_ref": "FIDYear [ref]",
    "financing": "Financing",
    "financing_ref": "Financing [ref]",
    "offshore": "Offshore",
    "floating": "Floating",
    "floating_vessel_name": "FloatingVesselName",
    "floating_vessel_name_ref": "FloatingVesselName [ref]",
    "vessel_owner": "VesselOwner",
    "vessel_owner_ref": "VesselOwner [ref]",
    "vessel_parent": "VesselParent",
    "vessel_operator": "VesselOperator",
    "vessel_operator_ref": "VesselOperator [ref]",
    "opposition": "Opposition",
    "esj_notes": "ESJNotes",
    "defeated": "Defeated",
    "pci_notes": "PCINotes",
    "pci3": "PCI3",
    "pci4": "PCI4",
    "pci5": "PCI5",
    "pci6": "PCI6",
    "lh2": "LH2",
    "nh3": "NH3",
    "synthetic_lng": "SyntheticLNG",
    "retrofit_proposed": "RetrofitProposed",
    "alt_fuel_prelim_agreement": "AltFuelPrelimAgreement",
    "alt_fuel_call_market_interest": "AltFuelCallMarketInterest",
    "ccs": "CCS",
    "ccs_notes": "CCSNotes",
}


def pull_postgres(out_path: Path, limit=None):
    """Primary path: flat all-fields export straight from the read-only Postgres."""
    from gem_query import get_database_url, build_engine, DEFAULT_STATEMENT_TIMEOUT_MS
    from gem_all_fields import export_all_fields

    engine = build_engine(get_database_url(), DEFAULT_STATEMENT_TIMEOUT_MS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = export_all_fields(engine, str(out_path), limit)
    print(f"  wrote {n:,} unit rows to {out_path}", file=sys.stderr)


def pull_via_web(out_path: Path, kind="lng"):
    """Fallback path: cookie-based download from the project-DB website."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(ROOT / "gem_export_via_web.py"), kind, "-o", str(out_path)],
    )
    if result.returncode != 0:
        sys.exit(f"ERROR: gem_export_via_web.py failed with exit code {result.returncode}")
    size = out_path.stat().st_size
    if size < 1000:
        sys.exit(f"ERROR: CSV suspiciously small ({size} bytes) — verify auth and try again")


def derive_column_map(csv_path: Path):
    """Read header row, return {canonical_name: 0-indexed-column} dict.
    Missing expected columns get None (so the caller can detect schema drift)."""
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            sys.exit(f"ERROR: empty CSV at {csv_path}")

    # The first column has a BOM in the empirical export — strip it
    if header and header[0].startswith("\ufeff"):
        header[0] = header[0][1:]

    col_map = {"_header_columns": header, "_total_columns": len(header)}

    for canonical, needle in EXPECTED_COLUMNS.items():
        idx = None
        for i, h in enumerate(header):
            if h.strip() == needle:
                idx = i
                break
        col_map[canonical] = idx

    canonical_headers = set(EXPECTED_COLUMNS.values())
    col_map["_unknown_columns"] = [h for h in header if h.strip() not in canonical_headers]
    return col_map


def report_and_save_map(col_map, out_path: Path):
    print(f"\nColumn-index map ({col_map['_total_columns']} total columns):")
    missing = [k for k, v in col_map.items() if not k.startswith("_") and v is None]
    for k, v in col_map.items():
        if k.startswith("_"):
            continue
        print(f"  {k:35} = {v if v is not None else '--':<5}{' [MISSING]' if v is None else ''}")

    if missing:
        print(f"\n  WARNING: {len(missing)} expected columns not found:")
        for k in missing:
            print(f"    {k}  (expected header text: {EXPECTED_COLUMNS[k]!r})")
        print("\n  Schema may have changed — check the live DB and update EXPECTED_COLUMNS.")

    if col_map["_unknown_columns"]:
        print(f"\n  NOTE: {len(col_map['_unknown_columns'])} unknown columns in header:")
        for h in col_map["_unknown_columns"]:
            print(f"    {h!r}")

    map_path = out_path.with_suffix(".colmap.json")
    serializable = {k: v for k, v in col_map.items() if k != "_header_columns"}
    serializable["_header_columns_count"] = col_map["_total_columns"]
    map_path.write_text(json.dumps(serializable, indent=2))
    print(f"\n  Column map saved to {map_path}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--output", "--out", dest="out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--map-only", action="store_true",
                   help="Skip the fetch; just derive the map from an existing CSV")
    p.add_argument("--via-web", action="store_true",
                   help="Use the cookie-based website download instead of Postgres")
    p.add_argument("--kind", default="lng", choices=["lng", "lng_export"],
                   help="Website export format for --via-web (default: lng, the 115-col all-fields)")
    p.add_argument("--limit", type=int, help="Plant-count cap for testing (Postgres path only)")
    args = p.parse_args()

    if not args.map_only:
        if args.via_web:
            pull_via_web(args.out, kind=args.kind)
        else:
            pull_postgres(args.out, limit=args.limit)

    report_and_save_map(derive_column_map(args.out), args.out)


if __name__ == "__main__":
    main()
