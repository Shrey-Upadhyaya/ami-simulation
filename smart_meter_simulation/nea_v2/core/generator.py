"""
NEA Reading Generator v2
=========================
Generates one 15-min interval reading per meter per slot.
Uses consumer-subtype-specific load profiles.
"""

import random, math
from config.load_profiles import (
    LOAD_PROFILES, SEASON_MULT, WEEKDAY_MOD,
    NOMINAL_V, NOMINAL_V_LN, LV_PROB, ANOMALY,
    PHASE_CURRENT_IMBALANCE, PHASE_VOLTAGE_VARIATION,
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

def _get_phase(subtype):
    spec = DOMESTIC_TYPES.get(subtype) or COMMERCIAL_TYPES.get(subtype, {})
    phase = spec.get("phase", "1P")
    if subtype == "COM_MV_11KV":  return "MV_11KV"
    if subtype == "COM_MV_33KV":  return "MV_33KV"
    return phase


def _voltage_1p(subtype, load_mult, feeder_km, is_outage):
    """Single-phase voltage. Returns (voltage_v, v_flag)."""
    if is_outage:
        return 0.0, "OUTAGE"
    phase = _get_phase(subtype)
    nom = NOMINAL_V.get(phase, 230.0)
    if subtype in ("COM_MV_11KV", "COM_MV_33KV"):
        v = nom * random.gauss(1.0, 0.005)
        return round(v, 1), None
    base_v = nom + random.gauss(0, 2.5)
    drop = load_mult * feeder_km * random.uniform(1.2, 3.0)
    v = base_v - drop
    tier = _load_tier(load_mult)
    if random.random() < LV_PROB[tier]:
        v, flag = random.uniform(nom * 0.83, nom * 0.93), "LOW_VOLTAGE"
    elif v > nom * 1.10:
        v, flag = random.uniform(nom * 1.10, nom * 1.13), "HIGH_VOLTAGE"
    else:
        flag = None
    return round(max(v, 0), 2), flag


def _voltage_3p(subtype, load_mult, feeder_km, is_outage):
    """Per-phase voltage for 3P (advanced metering). Returns ((va,vb,vc), v_flag)."""
    if is_outage:
        return (0.0, 0.0, 0.0), "OUTAGE"
    phase = _get_phase(subtype)
    nom_ln = NOMINAL_V_LN.get(phase, 230.0)
    var = PHASE_VOLTAGE_VARIATION
    if phase in ("MV_11KV", "MV_33KV"):
        va = nom_ln * random.gauss(1.0, 0.005)
        vb = nom_ln * random.gauss(1.0, 0.005)
        vc = nom_ln * random.gauss(1.0, 0.005)
        return (round(va, 1), round(vb, 1), round(vc, 1)), None
    base_v = nom_ln + random.gauss(0, 2.5)
    drop = load_mult * feeder_km * random.uniform(1.2, 3.0)
    v_centre = base_v - drop
    va = v_centre + random.uniform(-var, var)
    vb = v_centre + random.uniform(-var, var)
    vc = v_centre + random.uniform(-var, var)
    tier = _load_tier(load_mult)
    if random.random() < LV_PROB[tier]:
        band = (nom_ln * 0.83, nom_ln * 0.93)
        va, vb, vc = random.uniform(*band), random.uniform(*band), random.uniform(*band)
        flag = "LOW_VOLTAGE"
    elif max(va, vb, vc) > nom_ln * 1.10:
        band = (nom_ln * 1.10, nom_ln * 1.13)
        va = va if va < nom_ln * 1.10 else random.uniform(*band)
        vb = vb if vb < nom_ln * 1.10 else random.uniform(*band)
        vc = vc if vc < nom_ln * 1.10 else random.uniform(*band)
        flag = "HIGH_VOLTAGE"
    else:
        flag = None
    return (
        round(max(va, 0), 2), round(max(vb, 0), 2), round(max(vc, 0), 2)
    ), flag


def _current_1p(power_kw, voltage_v, pf):
    """Single-phase current. Returns (ia,)."""
    if voltage_v == 0:
        return (0.0,)
    ia = (power_kw * 1000) / (voltage_v * pf)
    return (round(ia, 3),)


def _current_3p(power_kw, v_ln_avg, pf, subtype):
    """Per-phase current for 3P with realistic imbalance. Returns (ia, ib, ic)."""
    if v_ln_avg == 0:
        return (0.0, 0.0, 0.0)
    phase = _get_phase(subtype)
    imb = PHASE_CURRENT_IMBALANCE
    fa = random.uniform(1 - imb, 1 + imb)
    fb = random.uniform(1 - imb, 1 + imb)
    fc = random.uniform(1 - imb, 1 + imb)
    total = fa + fb + fc
    fa, fb, fc = fa / total, fb / total, fc / total
    if phase in ("MV_11KV", "MV_33KV"):
        v_ll = {"MV_11KV": 11000.0, "MV_33KV": 33000.0}[phase]
        v_ln = v_ll / 1.732
    else:
        v_ln = v_ln_avg
    ia = (fa * power_kw * 1000) / (v_ln * pf)
    ib = (fb * power_kw * 1000) / (v_ln * pf)
    ic = (fc * power_kw * 1000) / (v_ln * pf)
    return round(ia, 3), round(ib, 3), round(ic, 3)


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

    # ── Electrical quantities (advanced metering: per-phase for 3P) ────────────
    pf      = round(random.uniform(0.82, 0.98), 3)
    phase   = _get_phase(subtype)
    is_3p   = phase in ("3P", "MV_11KV", "MV_33KV")

    if is_3p:
        (va, vb, vc), v_flag = _voltage_3p(subtype, combined, meter["feeder_length_km"], dtr_outage)
        v_ln_avg = (va + vb + vc) / 3 if (va or vb or vc) else 0
        ia, ib, ic = _current_3p(power_kw, v_ln_avg, pf, subtype)
        voltage_v = round((va + vb + vc) / 3, 2) if phase == "3P" else round(v_ln_avg, 1)
        current_a = max(ia, ib, ic)
    else:
        voltage_v, v_flag = _voltage_1p(subtype, combined, meter["feeder_length_km"], dtr_outage)
        ia = _current_1p(power_kw, voltage_v, pf)[0]
        current_a = ia
        ib = ic = None
        va = vb = vc = None

    freq_hz = round(random.gauss(50.0, 0.10), 3)

    # ── Energy delta (kWh for 15 min) ─────────────────────────────────────────
    import_kwh = round(power_kw * 0.25, 4)  # kW × 0.25 h

    # ── Comm loss ─────────────────────────────────────────────────────────────
    comm_lost = random.random() < ANOMALY["comm_loss_prob"]

    # ── Event flags ───────────────────────────────────────────────────────────
    flags = []
    if dtr_outage and outage_type: flags.append(outage_type)
    if v_flag:                     flags.append(v_flag)
    if tamper_flag:                flags.append(tamper_flag)

    # Base electrical (voltage_v, current_a kept for backward compat / aggregate)
    def _nv(x):
        return x if not comm_lost else None

    rec = {
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
        "import_kwh":      _nv(import_kwh),
        "active_power_kw": _nv(round(power_kw, 4)),
        "voltage_v":       _nv(voltage_v),
        "current_a":       _nv(current_a),
        "power_factor":    _nv(pf),
        "frequency_hz":    _nv(freq_hz),

        # Per-phase (advanced metering) — 1P: only _a populated, 3P: all three
        "voltage_an": _nv(va if is_3p else voltage_v),
        "voltage_bn": _nv(vb) if is_3p else None,
        "voltage_cn": _nv(vc) if is_3p else None,
        "current_a_ph":  _nv(ia),
        "current_b_ph":  _nv(ib) if is_3p else None,
        "current_c_ph":  _nv(ic) if is_3p else None,

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
    return rec
