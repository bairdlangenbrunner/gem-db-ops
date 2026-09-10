#!/usr/bin/env python3
"""
gem_colmap.py — the one implementation of "derive a header -> column-index map".

Every tracker pull in this repo writes a `<export>.colmap.json` next to its CSV
so downstream tooling never hard-codes column offsets: the exports drift between
GEM database revisions and backend-sheet edits (columns added, renamed,
reordered), and a hard-coded offset breaks silently rather than loudly.

This module owns both halves of that contract:

  * the canonical EXPECTED_COLUMNS maps (short canonical name -> exact header
    text) per tracker, which is what makes schema drift *detectable* — a
    `None` index in the output means the column the consumers ask for is gone;
  * derive / report / save, so all five pulls emit the same JSON shape.

Consumers (`lng-terminals-researcher`, `gogpt-researcher`, ...) import the maps
from here rather than keeping their own copies. Before 2026-08-11 the LNG map
was maintained in three places and drifted; don't reintroduce a copy.

JSON shape written to disk (stable — consumers depend on it):

    {
      "<short name>": 0-indexed column or null,   # one per EXPECTED_COLUMNS key
      "columns": {"<exact header text>": index},  # every column, unnamed ones too
      "_unknown_columns": ["<header>", ...],      # headers with no canonical name
      "_total_columns": 132,
      "_header_columns_count": 132,
      "_header_row": 0                            # 0-indexed row the header is on
    }

`_header_columns` (the raw header list) is deliberately NOT serialized — it is
re-derived from the CSV by the consumers' `colmap.load_colmap()`.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Canonical expected-column maps, one per tracker export.
#
# Key   = short canonical name consumers use (`colmap["capacity_mtpa"]`)
# Value = exact header text in the export
# ---------------------------------------------------------------------------

# LNG terminals (GGIT-LNG) — gem_all_fields.export_all_fields, 115 columns.
LNG_EXPECTED_COLUMNS: dict[str, str] = {
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

# Oil & gas power plants (GOGPT) — gem_all_fields.export_gogpt_all_fields,
# 86 columns. NB the export covers EVERY combustion unit (oil+gas+coal+bio);
# see gogpt/pull.py.
GOGPT_EXPECTED_COLUMNS: dict[str, str] = {
    "last_updated": "Last Updated",
    "researcher": "Researcher",
    "research_status": "Research status",
    "wiki_url": "Wiki URL",
    "country": "Country/Area",
    "plant_name": "Plant name",
    "plant_name_local": "Plant Name in Local Language / Script",
    "other_names": "Other Name(s)",
    "unit_name": "Unit name",
    "fuel": "Fuel",
    "fuel_ref": "Fuel Data Source",
    "num_engines": "Number Of Engines",
    "capacity_per_engine": "Capacity Per Engine",
    "capacity_mw": "Capacity (MW)",
    "capacity_ref": "Capacity Data Source",
    "status": "Status",
    "status_detail": "Status Detail",
    "status_ref": "Status Data Source",
    "conflict_disrupted": "Disrupted due to conflict",
    "conflict_disrupted_ref": "Disrupted due to conflict Data Source",
    "latest_activity": "Latest Activity",
    "latest_activity_ref": "Latest Activity Data Source",
    "cancellation_year": "Cancellation year",
    "cancellation_year_ref": "Cancellation year Data Source",
    "technology": "Turbine/Engine Technology",
    "technology_ref": "Turbine/Engine Technology Data Source",
    "equipment": "Equipment Manufacturer/Model",
    "equipment_ref": "Turbine/Engine Equipment Data Source",
    "chp": "CHP",
    "chp_ref": "CHP Data Source",
    "hydrogen_capable": "Hydrogen capable?",
    "hydrogen_notes": "Hydrogen Notes",
    "hydrogen_ref": "Hydrogen Data Source",
    "h2_ready_pct": "H2 ready turbine (%)?",
    "h2_mou": "MOU for H2 supply?",
    "h2_contract": "Contract for H2 supply?",
    "h2_financing": "Financing for supply of H2?",
    "h2_colocated": "Co-located with electrolyzer/H2 production facility?",
    "h2_blending_pct": "What % of H2 blending currently?",
    "h2_criteria_ref": "H2 Criteria Data Source",
    "ccs": "CCS attachment?",
    "ccs_ref": "CCS Data Source",
    "conversion": "Conversion/replacement?",
    "conversion_from_fuel": "Conversion from/replacement of (fuel)",
    "conversion_from_unit": "Conversion from/replacement of (GEM unit ID)",
    "conversion_ref": "Conversion/replacement Data Source",
    "conversion_to_fuel": "Conversion to (fuel)",
    "conversion_to_unit": "Conversion to (GEM unit ID)",
    "start_year": "Start year",
    "start_year_ref": "Start Year Data Source",
    "retired_year": "Retired year",
    "retired_year_ref": "Retired Year Data Source",
    "planned_retire": "Planned retire",
    "planned_retire_ref": "Planned Retire Data Source",
    "operator": "Operator(s)",
    "operator_ref": "Operators Data Source",
    "operator_entity_id": "Operator GEM Entity ID",
    "owner": "Owner(s)",
    "owner_entity_id": "Owner(s) GEM Entity ID",
    "owner_ref": "Owners Data Source",
    "parent": "Parent(s)",
    "parent_entity_id": "Parent GEM Entity ID",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "location_accuracy": "Location accuracy",
    "location_ref": "Location Data Source",
    "city": "City",
    "local_area": "Local area (taluk, county)",
    "major_area": "Major area (prefecture, district)",
    "state_province": "State/Province",
    "subregion": "Subregion",
    "region": "Region",
    "other_ids_location": "Other IDs (location)",
    "other_ids_unit": "Other IDs (unit)",
    "notes": "Notes",
    "captive_industry_use": "Captive industry use",
    "captive_industry_type": "Captive industry type",
    "captive_non_industry_use": "Captive non-industry use",
    "captive_ref": "Captive Data Source",
    "gem_location_id": "GEM location ID",
    "gem_unit_id": "GEM unit ID",
    "wepp_location_id": "WEPP location ID",
    "wepp_unit_id": "WEPP unit ID",
    "employment_notes": "Employment Notes",
    "employment_notes_ref": "Employment Notes Data Source",
    "linked_projects": "Linked Projects",
}

# Columns shared by the two pipeline tabs (GGIT gas / GOIT oil+NGL) in the
# backend Sheet. These are NOT a full column list — the tabs carry 132 / 107
# columns and researchers add more — just the ones consumers address by name.
# Everything else is still reachable through colmap["columns"][<header>].
_PIPELINE_SHARED_COLUMNS: dict[str, str] = {
    "network_grouping": "PipelineNetworkGrouping",
    "pipeline_name": "PipelineName",
    "segment_name": "SegmentName",
    "wiki": "Wiki",
    "project_id": "ProjectID",
    "other_english_names": "OtherEnglishNames",
    "other_language_name": "OtherLanguagePrimaryPipelineName",
    "status": "Status",
    "status_ref": "Status [ref]",
    "researcher": "Researcher",
    "last_updated": "LastUpdated",
    "fuel": "Fuel",
    "fuel_ref": "Fuel [ref]",
    "pipeline_type": "PipelineType",
    "countries": "CountriesOrAreas",
    "researcher_notes": "ResearcherNotes",
    "owner": "Owner",
    "parent": "Parent",
    "proposal_year": "ProposalYear",
    "construction_year": "ConstructionYear",
    "start_year_1": "StartYear1",
    "start_year_earliest": "StartYearEarliest",
    "start_ref": "Start [ref]",
    "shelved_year": "ShelvedYear",
    "cancelled_year": "CancelledYear",
    "stop_year": "StopYear",
    "shelved_cancelled_type": "ShelvedCancelledType",
    "capacity": "Capacity",
    "capacity_units": "CapacityUnits",
    "capacity_ref": "Capacity [ref]",
    "capacity_boed": "CapacityBOEd",
    "length_known": "LengthKnown",
    "length_known_units": "LengthKnownUnits",
    "length_known_km": "LengthKnownKm",
    "length_estimate_km": "LengthEstimateKm",
    "length_merged_km": "LengthMergedKm",
    "diameter": "Diameter",
    "diameter_mm": "DiameterInMm",
    "fuel_source": "FuelSource",
    "start_location": "StartLocation",
    "start_state_province": "StartState/Province",
    "start_country": "StartCountryOrArea",
    "start_region": "StartRegion",
    "start_subregion": "StartSubRegion",
    "end_location": "EndLocation",
    "end_state_province": "EndState/Province",
    "end_country": "EndCountryOrArea",
    "end_region": "EndRegion",
    "end_subregion": "EndSubRegion",
    "num_countries": "NumberOfCountries",
    "cost_usd": "CostUSD",
    "cost_euro": "CostEuro",
    "fid_status": "FIDStatus",
    "fid_year": "FIDYear",
    "opposition": "Opposition",
    "esj_notes": "ESJNotes",
    "route_type": "RouteType",
    "route_accuracy": "RouteAccuracy",
    "route_notes": "RouteNotes",
    "route_ref": "Route [ref]",
    "europe_tracker": "EuropeTracker",
    "pci3": "PCI3",
    "pci4": "PCI4",
    "pci5": "PCI5",
    # Columns present on BOTH tracker tabs: [ref] companions, month
    # granularity for the lifecycle years, unit columns, and the
    # start/end prefecture pair.
    "pipeline_type_ref": "PipelineType [ref]",
    "other_language_segment_name": "OtherLanguageSegmentName",
    "other_language_alternative_pipeline_names": "OtherLanguageAlternativePipelineNames",
    "background": "Background",
    "background_ref": "Background [ref]",
    "proposal_month": "ProposalMonth",
    "proposal_ref": "Proposal [ref]",
    "construction_month": "ConstructionMonth",
    "construction_ref": "Construction [ref]",
    "start_month_1": "StartMonth1",
    "start_year_2": "StartYear2",
    "start_year_2_month": "StartYear2Month",
    "start_year_3": "StartYear3",
    "start_year_3_month": "StartYear3Month",
    "delayed": "Delayed",
    "delay_type": "DelayType",
    "delay_ref": "Delay [ref]",
    "shelved_ref": "Shelved [ref]",
    "cancelled_ref": "Cancelled [ref]",
    "stop_ref": "Stop [ref]",
    "length_ref": "Length [ref]",
    "diameter_units": "DiameterUnits",
    "diameter_ref": "Diameter [ref]",
    "fuel_source_ref": "FuelSource [ref]",
    "start_prefecture_district": "StartPrefecture/District",
    "end_prefecture_district": "EndPrefecture/District",
    "fid_ref": "FID [ref]",
    "cost_usd_per_km": "CostUSDPerKm",
    "cost_euro_per_km": "CostEuroPerKm",
}

# GGIT gas pipelines — shared set plus the gas-only columns consumers use.
GGIT_EXPECTED_COLUMNS: dict[str, str] = {
    **_PIPELINE_SHARED_COLUMNS,
    "network_grouping_alt": "PipelineNetworkGroupingAlt",
    "parent_entity_ids": "ParentEntityIDs",
    "capacity_bcm": "CapacityBcm/y",
    "pressure": "Pressure",
    "length_double_counting": "LengthDoubleCounting",
    "location_ref": "Location [ref]",
    "project_level_cost": "ProjectLevelCost",
    "segment_cost": "SegmentCost",
    "pci6": "PCI6",
    "route_creator": "RouteCreator",
    "other_ids": "OtherIDs",
    "h2_notes": "H2Notes",
    "h2_pipeline_type": "H2PipelineType",
    "ccs_notes": "CCSNotes",
    "associated_lng_terminal": "AssociatedLNGTerminal",
    "pipeline_directionality": "PipelineDirectionality",
    "pressure_units": "PressureUnits",
    "pressure_ref": "Pressure [ref]",
    "project_level_cost_units": "ProjectLevelCostUnits",
    "project_level_cost_ref": "ProjectLevelCost [ref]",
    "segment_cost_units": "SegmentCostUnits",
    "segment_cost_year": "SegmentCostYear",
    "segment_cost_ref": "SegmentCost [ref]",
    "pci345_id": "PCI345ID",
    "pci6_id": "PCI6ID",
    "pci6_project_code": "PCI6ProjectCode",
    "draft_pci6_list": "DraftPCI6List",
    "draft_pci7": "DraftPCI7",
    "h2_repurposed_km": "H2RepurposedKm",
    "h2_new_build_km": "H2NewBuildKm",
    "h2_repurposed_pct": "H2Repurposed%",
    "h2_repurposed_km_or_pct_ref": "H2RepurposedKmOr% [ref]",
    "h2_pct": "H2%",
    "h2_proposed_year": "H2ProposedYear",
    "h2_start_year": "H2StartYear",
    "h2_cost": "H2Cost",
    "h2_cost_units": "H2CostUnits",
    "associated_with_us_lng_exports": "AssociatedWithUSLNGExports",
    "sci_grid_names": "SciGridNames",
}

# GOIT oil / NGL pipelines — shared set plus the oil-only columns.
GOIT_EXPECTED_COLUMNS: dict[str, str] = {
    **_PIPELINE_SHARED_COLUMNS,
    "network_grouping_alt": "AltPipelineNetworkGrouping",
    "owner_entity_ids": "OwnerEntityIDs",
    "disrupted": "Disrupted",
    "cost": "Cost",
    "cost_units": "CostUnits",
    "cost_ref": "Cost [ref]",
    "start_location_ref": "StartLocation [ref]",
    "end_location_ref": "EndLocation [ref]",
    "alternate_route_project_ids": "AlternateRouteProjectIDs",
    "associated_ethylene_cracker": "AssociatedEthyleneCrackerRMI",
    "cancelled_month": "CancelledMonth",
    "stop_month": "StopMonth",
    "opposition_ref": "Opposition [ref]",
    "opec_problems_al_ne": "OPEC/problems (for AL+NE)",
}

# Pipeline operators/owners tab — ProjectID-keyed, carries the Owner/Operator
# [ref] source columns the two tracker tabs don't.
PIPELINE_OWNERS_EXPECTED_COLUMNS: dict[str, str] = {
    "network_container": "PipelineNetworkContainer",
    "pipeline_name": "PipelineName",
    "segment_name": "SegmentName",
    "countries": "CountriesorAreas",
    "wiki": "Wiki",
    "project_id": "ProjectID",
    "researcher": "Researcher",
    "last_updated": "LastUpdated",
    "start_region": "StartRegion",
    "end_region": "EndRegion",
    "length_merged_km": "LengthMergedKm",
    "fuel": "Fuel",
    "status": "Status",
    "pci6": "PCI6",
    "aggregate_owners": "AggregateOwners",
    "notes_links": "Notes/Links",
    "operator": "Operator",
    "operator_ref": "Operator [ref]",
    "operator_local_language": "OperatorLocalLanguage",
    "qcc_owner": "QCCOwner(业主单位)",
    "owner_ref": "Owner [ref]",
    # Owner1..Owner11 + their percentages are the point of this tab; named
    # individually so consumers never index by offset.
    **{f"owner{n}": f"Owner{n}" for n in range(1, 12)},
    **{f"owner{n}_pct": f"Owner{n}%" for n in range(1, 12)},
    "percentage_verification": "Percentage Verification",
}

# Registry so callers can look a map up by tracker name.
EXPECTED_COLUMNS_BY_TRACKER: dict[str, dict[str, str]] = {
    "lng": LNG_EXPECTED_COLUMNS,
    "gogpt": GOGPT_EXPECTED_COLUMNS,
    "ggit": GGIT_EXPECTED_COLUMNS,
    "goit": GOIT_EXPECTED_COLUMNS,
    "pipeline_owners": PIPELINE_OWNERS_EXPECTED_COLUMNS,
}


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------

def read_header(csv_path, header_row: int = 0) -> list[str]:
    """Return the header row of a CSV as a list of strings, BOM stripped.

    `header_row` is 0-indexed: 0 for the Postgres exports, 2 for the pipeline
    tracker tabs (two preamble rows above the header) and 1 for the
    operators/owners tab. Rows above the header are skipped, not parsed.
    """
    csv_path = Path(csv_path)
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = None
        for i, row in enumerate(reader):
            if i == header_row:
                header = row
                break
        if header is None:
            sys.exit(f"ERROR: {csv_path} has no row {header_row} (empty or truncated CSV?)")
    if header and header[0].startswith("﻿"):
        header[0] = header[0][1:]
    return header


def derive(header: list[str], expected: dict[str, str] | None = None,
           header_row: int = 0) -> dict:
    """Build the colmap dict from a header row. See module docstring for shape."""
    stripped = [h.strip() for h in header]
    col_map: dict = {
        "_header_columns": header,
        "_total_columns": len(header),
        "_header_row": header_row,
    }

    expected = expected or {}
    for canonical, needle in expected.items():
        col_map[canonical] = stripped.index(needle) if needle in stripped else None

    # Every column by its exact header text, so consumers can reach columns
    # that have no canonical short name. First occurrence wins on duplicates.
    columns: dict[str, int] = {}
    for i, h in enumerate(stripped):
        columns.setdefault(h, i)
    col_map["columns"] = columns

    canonical_headers = set(expected.values())
    col_map["_unknown_columns"] = [h for h in stripped if h not in canonical_headers]
    return col_map


def derive_from_csv(csv_path, expected: dict[str, str] | None = None,
                    header_row: int = 0) -> dict:
    return derive(read_header(csv_path, header_row), expected, header_row)


def missing(col_map: dict, expected: dict[str, str]) -> list[str]:
    """Canonical names in `expected` that the header didn't contain."""
    return [k for k in expected if col_map.get(k) is None]


def report(col_map: dict, expected: dict[str, str] | None = None,
           show_indices: bool = True) -> list[str]:
    """Print the map (and any drift) to stdout. Returns the missing-name list."""
    expected = expected or {}
    print(f"\nColumn-index map ({col_map['_total_columns']} total columns):")
    if show_indices:
        for k in expected:
            v = col_map.get(k)
            flag = "" if v is not None else " [MISSING]"
            print(f"  {k:35} = {v if v is not None else '--':<5}{flag}")

    gone = missing(col_map, expected)
    if gone:
        print(f"\n  WARNING: {len(gone)} expected columns not found:")
        for k in gone:
            print(f"    {k}  (expected header text: {expected[k]!r})")
        print("\n  Schema may have changed — check the live backend and update "
              "EXPECTED_COLUMNS in gem_colmap.py.")

    unknown = col_map.get("_unknown_columns") or []
    if unknown:
        print(f"\n  NOTE: {len(unknown)} columns with no canonical short name:")
        for h in unknown:
            print(f"    {h!r}")
    return gone


def save(col_map: dict, csv_path) -> Path:
    """Write `<csv>.colmap.json` next to the CSV. Drops the raw header list."""
    map_path = Path(csv_path).with_suffix(".colmap.json")
    serializable = {k: v for k, v in col_map.items() if k != "_header_columns"}
    serializable["_header_columns_count"] = col_map["_total_columns"]
    map_path.write_text(json.dumps(serializable, indent=2))
    return map_path


def derive_report_save(csv_path, expected: dict[str, str] | None = None,
                       header_row: int = 0, show_indices: bool = True) -> dict:
    """The whole pull-script tail end: derive, print, write the .colmap.json."""
    col_map = derive_from_csv(csv_path, expected, header_row)
    report(col_map, expected, show_indices=show_indices)
    map_path = save(col_map, csv_path)
    print(f"\n  Column map saved to {map_path}", file=sys.stderr)
    return col_map


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Derive a .colmap.json from an existing export CSV's header row.")
    p.add_argument("csv", type=Path, help="Export CSV to read the header from")
    p.add_argument("--tracker", choices=sorted(EXPECTED_COLUMNS_BY_TRACKER),
                   help="Which canonical expected-column map to check against")
    p.add_argument("--header-row", type=int, default=None,
                   help="0-indexed header row (default: 0, or 2 for ggit/goit, "
                        "1 for pipeline_owners)")
    args = p.parse_args()

    default_header_row = {"ggit": 2, "goit": 2, "pipeline_owners": 1}
    header_row = (args.header_row if args.header_row is not None
                  else default_header_row.get(args.tracker, 0))
    derive_report_save(
        args.csv, EXPECTED_COLUMNS_BY_TRACKER.get(args.tracker), header_row,
    )
