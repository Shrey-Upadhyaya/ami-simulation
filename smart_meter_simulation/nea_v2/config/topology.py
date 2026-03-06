"""
NEA Simplified Topology Configuration
======================================
Fixed topology:
  1 Primary Substation
  └── 10 × 11kV Feeders
        └── N × Distribution Transformers  (auto-distributed)
              └── 1 × DCU per DTR
                    └── meters (domestic + commercial, ~100 per feeder)

All meter data flows to the single DCS (Data Collection System)
of this substation.

Urban Nepal consumer distribution (Kathmandu Valley basis):
  - Domestic  : 82%
  - Commercial: 18%

Domestic sub-distribution (based on NEA tariff data):
  Single Phase:
    5A   → 28%  (low-income, small flat, rural-urban migrant households)
    15A  → 42%  (standard middle-class household, most common)
    30A  → 8%   (larger residence, geyser + AC)
    60A  → 4%   (high-income bungalow)
  Three Phase:
    ≤10 kVA  → 8%   (large home, multiple ACs)
    10-25kVA → 7%   (affluent home with EV/elevator)
    >25kVA   → 3%   (mansion / apartment complex owner)

Commercial sub-distribution:
  Low Voltage:
    1P LV (small shop, clinic, salon)  → 45%
    3P LV (office, mid restaurant)     → 35%
  Medium Voltage:
    3P 11kV (hotel, mall, tower)       → 15%
    3P 33kV (large industrial/corp)    → 5%
"""

# ─── SUBSTATION ────────────────────────────────────────────────────────────────

SUBSTATION = {
    "pss_id":       "PSS_BALAJU_01",
    "pss_name":     "Balaju Primary Substation",
    "voltage_kv":   "132/11",
    "capacity_mva": 50.0,
    "latitude":     27.7370,
    "longitude":    85.3005,
    "dsc_id":       "DSC_KTM_CENTRAL",
    "dsc_name":     "NEA DCS — Balaju",   # Data Collection System
}

# ─── 10 FEEDERS ───────────────────────────────────────────────────────────────
# Each feeder has a character (residential-heavy, commercial strip, mixed, etc.)
# that influences consumer mix.  DTRs are auto-distributed by the builder.

FEEDERS = [
    # id, name, length_km, character, dom_pct, com_pct
    {"feeder_id": "FDR_01", "name": "Balaju Industrial Corridor", "length_km": 4.2, "dom_pct": 0.30, "com_pct": 0.70},
    {"feeder_id": "FDR_02", "name": "Swoyambhu Residential",      "length_km": 3.8, "dom_pct": 0.88, "com_pct": 0.12},
    {"feeder_id": "FDR_03", "name": "Nayabazar Mixed",            "length_km": 3.1, "dom_pct": 0.72, "com_pct": 0.28},
    {"feeder_id": "FDR_04", "name": "Machhapokhari Housing",      "length_km": 5.1, "dom_pct": 0.90, "com_pct": 0.10},
    {"feeder_id": "FDR_05", "name": "Ring Road Commercial",       "length_km": 2.9, "dom_pct": 0.45, "com_pct": 0.55},
    {"feeder_id": "FDR_06", "name": "Sitapaila Colony",           "length_km": 4.6, "dom_pct": 0.85, "com_pct": 0.15},
    {"feeder_id": "FDR_07", "name": "Nagarjun Slope",             "length_km": 6.3, "dom_pct": 0.92, "com_pct": 0.08},
    {"feeder_id": "FDR_08", "name": "Balaju Bazar",               "length_km": 2.4, "dom_pct": 0.55, "com_pct": 0.45},
    {"feeder_id": "FDR_09", "name": "Tarakeshwor South",          "length_km": 3.7, "dom_pct": 0.80, "com_pct": 0.20},
    {"feeder_id": "FDR_10", "name": "Industrial Estate North",    "length_km": 5.5, "dom_pct": 0.25, "com_pct": 0.75},
]

METERS_PER_FEEDER = 100   # fixed per spec

# ─── CONSUMER TYPE DEFINITIONS ────────────────────────────────────────────────

# Domestic consumer sub-types
# key → (label, phase, ampere_or_kva, voltage_v, base_load_kw, weight)
DOMESTIC_TYPES = {
    "DOM_SP_5A":    {
        "label":       "Domestic Single Phase 5A",
        "phase":       "1P", "ampere": 5,   "voltage_v": 230,
        "base_load_kw": 0.60,   # 0.6 kW connected load (fan, lights, small TV)
        "weight":       0.28,
        "tariff":       "D1",   # NEA Domestic tariff ≤ 150 units/month
        "typical_monthly_kwh": (20, 80),
    },
    "DOM_SP_15A":   {
        "label":       "Domestic Single Phase 15A",
        "phase":       "1P", "ampere": 15,  "voltage_v": 230,
        "base_load_kw": 2.0,
        "weight":       0.42,
        "tariff":       "D2",   # NEA Domestic 150-400 units/month
        "typical_monthly_kwh": (80, 250),
    },
    "DOM_SP_30A":   {
        "label":       "Domestic Single Phase 30A",
        "phase":       "1P", "ampere": 30,  "voltage_v": 230,
        "base_load_kw": 4.5,
        "weight":       0.08,
        "tariff":       "D3",
        "typical_monthly_kwh": (250, 500),
    },
    "DOM_SP_60A":   {
        "label":       "Domestic Single Phase 60A",
        "phase":       "1P", "ampere": 60,  "voltage_v": 230,
        "base_load_kw": 8.0,
        "weight":       0.04,
        "tariff":       "D3",
        "typical_monthly_kwh": (400, 900),
    },
    "DOM_3P_10KVA": {
        "label":       "Domestic Three Phase ≤10 kVA",
        "phase":       "3P", "kva": 10,     "voltage_v": 400,
        "base_load_kw": 6.0,
        "weight":       0.08,
        "tariff":       "D3",
        "typical_monthly_kwh": (350, 700),
    },
    "DOM_3P_25KVA": {
        "label":       "Domestic Three Phase 10–25 kVA",
        "phase":       "3P", "kva": 25,     "voltage_v": 400,
        "base_load_kw": 14.0,
        "weight":       0.07,
        "tariff":       "D3",
        "typical_monthly_kwh": (700, 1800),
    },
    "DOM_3P_25KVA_PLUS": {
        "label":       "Domestic Three Phase >25 kVA",
        "phase":       "3P", "kva": 50,     "voltage_v": 400,
        "base_load_kw": 28.0,
        "weight":       0.03,
        "tariff":       "D3",
        "typical_monthly_kwh": (1500, 4000),
    },
}

# Commercial consumer sub-types
COMMERCIAL_TYPES = {
    "COM_LV_1P":    {
        "label":       "Commercial LV Single Phase",
        "phase":       "1P", "voltage_v": 230, "supply_level": "LV",
        "base_load_kw": 3.0,
        "weight":       0.45,
        "tariff":       "C1",   # NEA Commercial LV
        "typical_monthly_kwh": (120, 500),
        "examples":    "Small shop, salon, clinic, cyber cafe",
    },
    "COM_LV_3P":    {
        "label":       "Commercial LV Three Phase",
        "phase":       "3P", "voltage_v": 400, "supply_level": "LV",
        "base_load_kw": 12.0,
        "weight":       0.35,
        "tariff":       "C2",
        "typical_monthly_kwh": (500, 3000),
        "examples":    "Office block, restaurant, mid-size hotel",
    },
    "COM_MV_11KV":  {
        "label":       "Commercial MV 11kV",
        "phase":       "3P", "voltage_kv": "11kV", "supply_level": "MV",
        "base_load_kw": 80.0,
        "weight":       0.15,
        "tariff":       "C3",   # NEA Commercial MV
        "typical_monthly_kwh": (8000, 60000),
        "examples":    "Large hotel, mall, corporate tower",
    },
    "COM_MV_33KV":  {
        "label":       "Commercial MV 33kV",
        "phase":       "3P", "voltage_kv": "33kV", "supply_level": "MV",
        "base_load_kw": 250.0,
        "weight":       0.05,
        "tariff":       "C4",
        "typical_monthly_kwh": (50000, 300000),
        "examples":    "Large industrial complex, data center, hospital",
    },
}

# Overall urban Nepal domestic vs commercial split
URBAN_DOM_PCT = 0.82
URBAN_COM_PCT = 0.18

# ─── DTR AUTO-DISTRIBUTION RULES ─────────────────────────────────────────────
# DTRs are auto-placed per feeder based on meter count and consumer types.
# MV commercial consumers get their own dedicated DTR (metered at 11/33kV).
# LV consumers are grouped under shared DTRs.

# Standard DTR capacities (kVA) available
DTR_CAPACITIES_KVA = [25, 50, 100, 160, 200, 250, 315, 400]

# Max LV consumers per DTR (prevents overloading)
MAX_LV_METERS_PER_DTR = 25   # ~10–25 is standard NEA practice

# MV commercial consumers: 1 consumer = 1 dedicated DTR/metering point
MV_DEDICATED_DTR = True

# ─── NOMINAL VOLTAGE & TOLERANCE ─────────────────────────────────────────────
NOMINAL_LV_V   = 230.0    # single phase
NOMINAL_LV_3P  = 400.0    # three phase LV
VOLTAGE_BAND   = 0.10     # ±10% (IEC 60038 / Nepal standard)
