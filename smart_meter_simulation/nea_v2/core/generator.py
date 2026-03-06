"""
NEA Reading Generator v2
=========================
Generates one 15-min interval reading per meter per slot.
Uses consumer-subtype-specific load profiles.
"""

import random, math
from config.load_profiles import (
    LOAD_PROFILES, SEASON_MULT, WEEKDAY_MOD,
    NOMINAL_V, LV_PROB, ANOMALY
)
from config.topology import DOMESTIC_TYPES, COMMERCIAL_TYPES

NPT_OFFSET_H = 5.75   # UTC+5:45 as decimal hours


def _slot(dt):
    return dt.hour * 4 + dt.minute // 15

def _load_tier(m):
    if m < 0.20: return "off_peak"
    if m < 0.50: return "mid"
    if m < 0.75: return "peak"
    return "critical"

def _voltage(subtype, load_mult, feeder_km, is_outage):
    if is_outage:
        return 0.0, "OUTAGE"

    phase = _get_phase(subtype)
    nom   = NOMINAL_V.get(phase, 230.0)

    # MV consumers: voltage is at 11kV/33kV — much more stable
    if subtype in ("COM_MV_11KV", "COM_MV_33KV"):
        v = nom * random.gauss(1.0, 0.005)
        return round(v, 1), None

    # LV: subject to feeder drop
    base_v = nom + random.gauss(0, 2.5)
    drop   = load_mult * feeder_km * random.uniform(1.2, 3.0)
    v      = base_v - drop

    tier = _load_tier(load_mult)
    if random.random() < LV_PROB[tier]:
        v    = random.uniform(nom * 0.83, nom * 0.93)  # low voltage band
        flag = "LOW_VOLTAGE"
    elif v > nom * 1.10:
        v    = random.uniform(nom * 1.10, nom * 1.13)
        flag = "HIGH_VOLTAGE"
    else:
        flag = None

    return round(max(v, 0), 2), flag

def _get_phase(subtype):
    spec = DOMESTIC_TYPES.get(subtype) or COMMERCIAL_TYPES.get(subtype, {})
    phase = spec.get("phase", "1P")
    if subtype == "COM_MV_11KV":  return "MV_11KV"
    if subtype == "COM_MV_33KV":  return "MV_33KV"
    return phase

def _current(power_kw, voltage_v, pf, subtype):
    if voltage_v == 0: return 0.0
    phase = _get_phase(subtype)
    if phase == "3P":
        # I = P / (√3 × V_LL × PF)
        return round((power_kw * 1000) / (1.732 * voltage_v * pf), 3)
    elif phase in ("MV_11KV", "MV_33KV"):
        v_ll = {"MV_11KV": 11000.0, "MV_33KV": 33000.0}[phase]
        return round((power_kw * 1000) / (1.732 * v_ll * pf), 3)
    else:
        # 1P: I = P / (V × PF)
        return round((power_kw * 1000) / (voltage_v * pf), 3)


def generate_reading(meter, dt_npt, dtr_outage=False, outage_type=None):
    subtype  = meter["consumer_subtype"]
    category = meter["consumer_category"]
    base_kw  = meter["base_load_kw"]
    slot     = _slot(dt_npt)
    weekday  = dt_npt.weekday()
    month    = dt_npt.month

    # ── Load profile ─────────────────────────────────────────────────────────
    profile_mult = LOAD_PROFILES[subtype][slot]

    # ── Weekday modifier ──────────────────────────────────────────────────────
    wd_dom, wd_com = WEEKDAY_MOD[weekday]
    wd_mod = wd_dom if category == "DOM" else wd_com

    # ── Seasonal modifier ─────────────────────────────────────────────────────
    seas_dom, seas_com = SEASON_MULT[month]
    seas_mod = seas_dom if category == "DOM" else seas_com

    # ── Gaussian noise ────────────────────────────────────────────────────────
    noise = random.gauss(1.0, 0.07)

    combined = max(0.02, profile_mult * wd_mod * seas_mod * noise)

    # ── Actual power ──────────────────────────────────────────────────────────
    power_kw = base_kw * combined

    # ── Tamper bypass ─────────────────────────────────────────────────────────
    tamper_flag = None
    if meter["is_tampered"]:
        power_kw *= (1.0 - meter["tamper_bypass_pct"])
        if random.random() < 0.003:
            tamper_flag = random.choice([
                "COVER_OPEN","MAGNETIC_TAMPER","CURRENT_REVERSAL","NEUTRAL_DISTURBANCE"
            ])

    # ── Outage ────────────────────────────────────────────────────────────────
    if dtr_outage:
        power_kw = 0.0

    # ── Electrical quantities ─────────────────────────────────────────────────
    pf        = round(random.uniform(0.82, 0.98), 3)
    voltage_v, v_flag = _voltage(subtype, combined, meter["feeder_length_km"], dtr_outage)
    current_a = _current(power_kw, voltage_v, pf, subtype)
    freq_hz   = round(random.gauss(50.0, 0.10), 3)

    # ── Energy delta (kWh for 15 min) ─────────────────────────────────────────
    import_kwh = round(power_kw * 0.25, 4)  # kW × 0.25 h

    # ── Comm loss ─────────────────────────────────────────────────────────────
    comm_lost = random.random() < ANOMALY["comm_loss_prob"]

    # ── Event flags ───────────────────────────────────────────────────────────
    flags = []
    if dtr_outage and outage_type: flags.append(outage_type)
    if v_flag:                     flags.append(v_flag)
    if tamper_flag:                flags.append(tamper_flag)

    return {
        # Identity + classification
        "meter_id":          meter["meter_id"],
        "meter_serial":      meter["meter_serial"],
        "consumer_id":       meter["consumer_id"],
        "consumer_name":     meter["consumer_name"],
        "consumer_category": category,
        "consumer_subtype":  subtype,
        "consumer_label":    meter["consumer_label"],
        "tariff_code":       meter["tariff_code"],
        "phase":             meter["phase"],
        "supply_level":      meter["supply_level"],

        # Topology (denormalized for fast query)
        "dcs_id":    meter["dcs_id"],
        "pss_id":    meter["pss_id"],
        "feeder_id": meter["feeder_id"],
        "dtr_id":    meter["dtr_id"],
        "dcu_id":    meter["dcu_id"],

        # Time (Nepal Time UTC+5:45)
        "timestamp_npt":  dt_npt.strftime("%Y-%m-%d %H:%M:%S"),
        "date":           dt_npt.date().isoformat(),
        "time_slot":      slot,
        "hour":           dt_npt.hour,
        "weekday":        weekday,
        "month":          month,
        "is_saturday":    weekday == 5,   # Saturday = holiday Nepal

        # Electrical measurements (null on comm loss)
        "import_kwh":      import_kwh if not comm_lost else None,
        "active_power_kw": round(power_kw, 4) if not comm_lost else None,
        "voltage_v":       voltage_v if not comm_lost else None,
        "current_a":       current_a if not comm_lost else None,
        "power_factor":    pf        if not comm_lost else None,
        "frequency_hz":    freq_hz   if not comm_lost else None,

        # Status
        "event_flags":     "|".join(flags) if flags else None,
        "is_outage":       dtr_outage,
        "is_comm_loss":    comm_lost,
        "is_voltage_event":v_flag is not None,
        "is_tamper_event": tamper_flag is not None,

        # Ground truth (for ML/analytics)
        "gt_is_tampered":       meter["is_tampered"],
        "gt_tamper_bypass_pct": meter["tamper_bypass_pct"],
        "dbg_profile_mult":     round(profile_mult, 4),
        "dbg_combined_mult":    round(combined, 4),
    }
