"""
NEA Infrastructure Builder v2
==============================
Builds:
  1 Substation → 10 Feeders → auto-distributed DTRs → 1 DCU per DTR → 100 meters/feeder

DTR auto-distribution logic:
  - MV commercial consumers (11kV/33kV) get a dedicated DTR each
  - LV consumers are grouped: max MAX_LV_METERS_PER_DTR per DTR
  - DTR capacity is sized to the load it serves
"""

import uuid, random
from collections import defaultdict
from config.topology import (
    SUBSTATION, FEEDERS, METERS_PER_FEEDER,
    DOMESTIC_TYPES, COMMERCIAL_TYPES,
    URBAN_DOM_PCT, URBAN_COM_PCT,
    DTR_CAPACITIES_KVA, MAX_LV_METERS_PER_DTR,
)

# ─── Nepali name banks ────────────────────────────────────────────────────────
_SURNAMES  = ["Shrestha","Maharjan","Tamang","Gurung","Thapa","Karki","Poudel",
              "Adhikari","Bhattarai","Pandey","Sharma","Acharya","Joshi","Rai",
              "Limbu","Magar","Bajracharya","Tuladhar","Manandhar","Pradhan",
              "Rajbhandari","KC","Bista","Regmi","Koirala","Dahal","Upreti"]
_GIVEN     = ["Ramesh","Sita","Bishnu","Maya","Hari","Gita","Suresh","Puja",
              "Dipak","Sunita","Prakash","Kopila","Binod","Anita","Rajesh",
              "Sangita","Santosh","Rekha","Nabin","Sabina","Bikash","Srijana",
              "Dinesh","Kamala","Roshan","Nirmala","Sunil","Sarita","Anil","Rita"]
_COM_NAMES = ["Sewa Pasal","Nepal Mart","Himalayan Store","Everest Traders",
              "Buddha Hotel","Annapurna Restaurant","Pashupatinath Bakery",
              "Kathmandu Cafe","Valley Electronics","Sunrise Hardware",
              "Om Medical Hall","Ganapati Cloth House","Mero Kiryana",
              "Swastik Stationery","Laxmi General Store","Mandala Boutique",
              "Trishul IT Center","Ganesh Auto Parts","Shiva Welding Works",
              "Kumari Beauty Parlor","Summit Lodge","Yak & Yeti Annexe",
              "Sagarmatha Holdings","Mustang Trading Co","Pokhara Suppliers"]

def _dom_name():  return f"{random.choice(_GIVEN)} {random.choice(_SURNAMES)}"
def _com_name():
    base = random.choice(_COM_NAMES)
    return base if random.random() < 0.55 else f"{base} Pvt. Ltd."

def _pick_dom_subtype():
    types  = list(DOMESTIC_TYPES.keys())
    weights = [DOMESTIC_TYPES[t]["weight"] for t in types]
    return random.choices(types, weights=weights, k=1)[0]

def _pick_com_subtype():
    types  = list(COMMERCIAL_TYPES.keys())
    weights = [COMMERCIAL_TYPES[t]["weight"] for t in types]
    return random.choices(types, weights=weights, k=1)[0]

def _is_mv(subtype):
    return subtype in ("COM_MV_11KV", "COM_MV_33KV")

def _size_dtr(meters_under_it):
    """Pick smallest DTR capacity that comfortably serves these meters."""
    # Rough estimate: sum of base loads × diversity factor 0.6
    total_kw = sum(
        _get_base_load(m["consumer_subtype"]) for m in meters_under_it
    ) * 0.60
    total_kva = total_kw / 0.85   # PF assumption
    for cap in DTR_CAPACITIES_KVA:
        if cap >= total_kva:
            return cap
    return DTR_CAPACITIES_KVA[-1]  # 400 kVA max

def _get_base_load(subtype):
    if subtype in DOMESTIC_TYPES:
        return DOMESTIC_TYPES[subtype]["base_load_kw"]
    return COMMERCIAL_TYPES[subtype]["base_load_kw"]

def _dcu_record(dtr_id, pss_id, n_meters, feeder_id=""):
    return {
        "dcu_id":          str(uuid.uuid4()),
        "dcu_serial":      f"DCU{random.randint(10000,99999)}",
        "vendor":          random.choice(["Itron","Landis+Gyr","Wasion","L&G","Iskraemeco"]),
        "model":           "RFC-2400",
        "firmware":        f"v{random.randint(2,4)}.{random.randint(0,9)}.{random.randint(0,9)}",
        "comm_tech":       "GPRS",
        "ip_address":      f"10.{random.randint(1,9)}.{random.randint(1,255)}.{random.randint(1,254)}",
        "meter_capacity":  50,
        "connected_meters":n_meters,
        "status":          "ONLINE",
        "dtr_id":          dtr_id,
        "pss_id":          pss_id,
        "feeder_id":       feeder_id,
        "hes_id":          "HES_BALAJU_01",
        "dcs_id":          "DCS_BALAJU_01",
    }


def build_infrastructure(seed=42):
    """
    Returns:
        meters  : list of meter dicts (1000 total)
        dtrs    : list of DTR dicts
        dcus    : list of DCU dicts
        feeders : feeder list with stats populated
    """
    random.seed(seed)
    pss = SUBSTATION
    all_meters, all_dtrs, all_dcus = [], [], []

    print(f"\n🏗️  Building NEA infrastructure — {pss['pss_name']}")
    print(f"   DCS: {pss['dsc_name']}")
    print(f"   Feeders: {len(FEEDERS)}  |  Meters/feeder: {METERS_PER_FEEDER}\n")

    for feeder in FEEDERS:
        fdr_id     = feeder["feeder_id"]
        dom_pct    = feeder["dom_pct"]
        com_pct    = feeder["com_pct"]

        lat_base   = pss["latitude"]  + random.uniform(-0.010, 0.010)
        lon_base   = pss["longitude"] + random.uniform(-0.010, 0.010)

        # ── Step 1: assign consumer type to each of the 100 meter slots ──────
        n_dom = round(METERS_PER_FEEDER * dom_pct)
        n_com = METERS_PER_FEEDER - n_dom

        raw_consumers = []
        for _ in range(n_dom):
            st = _pick_dom_subtype()
            raw_consumers.append({"category": "DOM", "subtype": st, "is_mv": False})
        for _ in range(n_com):
            st = _pick_com_subtype()
            raw_consumers.append({"category": "COM", "subtype": st, "is_mv": _is_mv(st)})

        random.shuffle(raw_consumers)

        # ── Step 2: separate MV consumers (dedicated DTR each) vs LV ─────────
        mv_consumers = [c for c in raw_consumers if c["is_mv"]]
        lv_consumers = [c for c in raw_consumers if not c["is_mv"]]

        # ── Step 3: group LV consumers into DTRs ─────────────────────────────
        lv_groups = []
        for i in range(0, len(lv_consumers), MAX_LV_METERS_PER_DTR):
            lv_groups.append(lv_consumers[i:i + MAX_LV_METERS_PER_DTR])

        # ── Step 4: build meters, DTRs, DCUs ─────────────────────────────────
        dtr_counter = 0

        # LV DTRs
        for group in lv_groups:
            dtr_counter += 1
            dtr_id  = f"DTR_{fdr_id}_{dtr_counter:02d}"
            dtr_lat = lat_base + random.uniform(-0.008, 0.008)
            dtr_lon = lon_base + random.uniform(-0.008, 0.008)

            # placeholder to size DTR after building meter records
            group_meter_placeholders = []
            for cons in group:
                group_meter_placeholders.append({
                    "consumer_subtype": cons["subtype"],
                    "category": cons["category"],
                })

            capacity_kva = _size_dtr(group_meter_placeholders)
            dtr = {
                "dtr_id":          dtr_id,
                "dtr_serial":      f"DTR{random.randint(100000,999999)}",
                "capacity_kva":    capacity_kva,
                "voltage_ratio":   "11kV/400V",
                "dtr_type":        "LV_SHARED",
                "latitude":        round(dtr_lat, 6),
                "longitude":       round(dtr_lon, 6),
                "feeder_id":       fdr_id,
                "feeder_name":     feeder["name"],
                "pss_id":          pss["pss_id"],
                "pss_name":        pss["pss_name"],
                "dcs_id":          "DCS_BALAJU_01",
            }
            all_dtrs.append(dtr)

            dcu = _dcu_record(dtr_id, pss["pss_id"], len(group), fdr_id)
            all_dcus.append(dcu)

            for cons in group:
                all_meters.append(
                    _build_meter(cons, dtr, dcu, feeder, pss, lat_base, lon_base)
                )

        # MV dedicated DTRs (metering point = 11kV/33kV)
        for cons in mv_consumers:
            dtr_counter += 1
            dtr_id  = f"DTR_{fdr_id}_{dtr_counter:02d}_MV"
            dtr_lat = lat_base + random.uniform(-0.008, 0.008)
            dtr_lon = lon_base + random.uniform(-0.008, 0.008)
            vkv     = COMMERCIAL_TYPES[cons["subtype"]].get("voltage_kv", "11kV")
            cap     = 400 if vkv == "11kV" else 1600   # 1600 kVA for 33kV

            dtr = {
                "dtr_id":          dtr_id,
                "dtr_serial":      f"DTR{random.randint(100000,999999)}",
                "capacity_kva":    cap,
                "voltage_ratio":   f"{vkv}/400V",
                "dtr_type":        "MV_DEDICATED",
                "latitude":        round(dtr_lat, 6),
                "longitude":       round(dtr_lon, 6),
                "feeder_id":       fdr_id,
                "feeder_name":     feeder["name"],
                "pss_id":          pss["pss_id"],
                "pss_name":        pss["pss_name"],
                "dcs_id":          "DCS_BALAJU_01",
            }
            all_dtrs.append(dtr)

            dcu = _dcu_record(dtr_id, pss["pss_id"], 1, fdr_id)
            all_dcus.append(dcu)

            all_meters.append(
                _build_meter(cons, dtr, dcu, feeder, pss, lat_base, lon_base)
            )

        print(f"  ✓ {feeder['feeder_id']} — {feeder['name']:<35} "
              f"DOM:{n_dom:3d}  COM:{n_com:3d}  "
              f"DTRs:{dtr_counter:3d}  DCUs:{dtr_counter:3d}")

    _print_summary(all_meters, all_dtrs, all_dcus)
    return all_meters, all_dtrs, all_dcus


def _build_meter(cons, dtr, dcu, feeder, pss, lat_base, lon_base):
    subtype  = cons["subtype"]
    category = cons["category"]
    is_dom   = category == "DOM"
    spec     = DOMESTIC_TYPES[subtype] if is_dom else COMMERCIAL_TYPES[subtype]
    is_tampered = random.random() < 0.015

    meter_lat = lat_base + random.uniform(-0.010, 0.010)
    meter_lon = lon_base + random.uniform(-0.010, 0.010)

    return {
        # Identity
        "meter_id":          str(uuid.uuid4()),
        "meter_serial":      f"NEA{random.randint(10000000,99999999)}",
        "meter_type":        random.choice(["Secure Elite 310","L&G E350",
                                            "Wasion WFET-201","Itron ACE1000"]),
        "consumer_name":     _dom_name() if is_dom else _com_name(),
        "consumer_id":       f"KTM-{random.randint(100000,999999)}",

        # Classification
        "consumer_category": category,          # DOM / COM
        "consumer_subtype":  subtype,
        "consumer_label":    spec["label"],
        "tariff_code":       spec["tariff"],
        "phase":             spec["phase"],
        "supply_level":      spec.get("supply_level", "LV"),
        "rated_ampere":      spec.get("ampere", None),
        "rated_kva":         spec.get("kva", None),
        "voltage_v":         spec.get("voltage_v", spec.get("voltage_kv", 230)),
        "base_load_kw":      round(spec["base_load_kw"] * random.uniform(0.85, 1.15), 3),

        # Infrastructure hierarchy
        "dcs_id":            "DCS_BALAJU_01",
        "pss_id":            pss["pss_id"],
        "pss_name":          pss["pss_name"],
        "feeder_id":         feeder["feeder_id"],
        "feeder_name":       feeder["name"],
        "feeder_length_km":  feeder["length_km"],
        "dtr_id":            dtr["dtr_id"],
        "dtr_type":          dtr["dtr_type"],
        "dcu_id":            dcu["dcu_id"],

        # Location
        "latitude":          round(meter_lat, 6),
        "longitude":         round(meter_lon, 6),

        # Anomaly ground truth
        "is_tampered":       is_tampered,
        "tamper_bypass_pct": round(random.uniform(0.30, 0.75), 2) if is_tampered else 0.0,

        # Cumulative register starting point
        "register_start_kwh": round(random.uniform(200, 95000), 1),
    }


def _print_summary(meters, dtrs, dcus):
    from collections import Counter
    cat_counts  = Counter(m["consumer_category"] for m in meters)
    sub_counts  = Counter(m["consumer_subtype"]  for m in meters)
    phase_counts= Counter(m["phase"]             for m in meters)
    tariff_c    = Counter(m["tariff_code"]       for m in meters)

    print(f"\n{'─'*60}")
    print(f"  Total meters : {len(meters):,}")
    print(f"  Total DTRs   : {len(dtrs):,}  (LV shared + MV dedicated)")
    print(f"  Total DCUs   : {len(dcus):,}  (1 per DTR)")
    print(f"\n  Consumer category:")
    for k, v in sorted(cat_counts.items()):
        print(f"    {k:8s}: {v:4d}  ({100*v/len(meters):.1f}%)")
    print(f"\n  Consumer sub-types:")
    for k, v in sorted(sub_counts.items(), key=lambda x: -x[1]):
        print(f"    {k:<20}: {v:4d}  ({100*v/len(meters):.1f}%)")
    print(f"\n  Phase distribution:")
    for k, v in sorted(phase_counts.items()):
        print(f"    {k:5s}: {v:4d}  ({100*v/len(meters):.1f}%)")
    print(f"\n  Tariff distribution:")
    for k, v in sorted(tariff_c.items()):
        print(f"    {k:4s}: {v:4d}  ({100*v/len(meters):.1f}%)")
    print(f"{'─'*60}\n")
