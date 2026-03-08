"""
Nepal Urban Load Profiles — 15-minute intervals (96 slots/day)
================================================================
Profiles are shaped from NEA demand study observations and
Kathmandu Valley consumption behaviour research.

Index 0 = 00:00 NPT (Nepal Time UTC+5:45)
Value  = fraction of base_load_kw active at that slot

Domestic sub-type profiles reflect appliance ownership:
  5A  → fans, LED lights, phone charging, small TV
  15A → above + geyser (instant), small AC/cooler, fridge
  30A → above + washing machine, larger AC, water pump
  60A → above + multiple ACs, EV charging, home theatre

Commercial profiles reflect operating hours:
  LV_1P → small shop: 9AM–9PM daily
  LV_3P → office/mid-hotel: 9AM–10PM, restaurant spikes
  MV_11KV → large hotel: 24h with night baseload
  MV_33KV → industrial: near-constant with shift peaks
"""

import math

NPT_WORK_START = 10.0    # Government offices open 10:00 AM Nepal
NPT_SHOP_OPEN  = 9.5     # Shops open ~9:30 AM
NPT_SHOP_CLOSE = 21.0    # Most shops close 9 PM

def _gaussian(hour, centre, sigma, height):
    return height * math.exp(-0.5 * ((hour - centre) / sigma) ** 2)

# ─── DOMESTIC PROFILES ────────────────────────────────────────────────────────

def _dom_5a_profile():
    """5A household: fan, LED lights, phone charger, small TV."""
    p = []
    for i in range(96):
        h = i / 4.0
        base   = 0.10
        morn   = _gaussian(h, 6.0,  0.5,  0.20)
        eve    = _gaussian(h, 19.5, 1.5,  0.70)
        p.append(round(min(base + morn + eve, 1.0), 4))
    return p

def _dom_15a_profile():
    """15A household: fridge, fan, lights, geyser, small AC."""
    p = []
    for i in range(96):
        h = i / 4.0
        base   = 0.12
        pump   = _gaussian(h, 6.0,  0.60, 0.55)
        daytime= _gaussian(h, 13.0, 2.0,  0.12)
        evening= _gaussian(h, 19.75,1.5,  0.80)
        late   = _gaussian(h, 20.75,0.6,  0.18)
        p.append(round(min(base + pump + daytime + evening + late, 1.0), 4))
    return p

def _dom_30a_profile():
    """30A household: washing machine, larger AC, water pump."""
    p = []
    for i in range(96):
        h = i / 4.0
        base   = 0.14
        pump   = _gaussian(h, 6.0,  0.50, 0.55)
        wash   = _gaussian(h, 8.5,  0.75, 0.35)
        ac     = _gaussian(h, 14.5, 2.5,  0.25)
        evening= _gaussian(h, 19.5, 1.4,  0.82)
        late   = _gaussian(h, 21.0, 0.5,  0.15)
        p.append(round(min(base + pump + wash + ac + evening + late, 1.0), 4))
    return p

def _dom_60a_profile():
    """60A household: multiple ACs, EV charger, home theatre."""
    p = []
    for i in range(96):
        h = i / 4.0
        base    = 0.18
        pump    = _gaussian(h, 6.25, 0.60, 0.50)
        morning = _gaussian(h, 8.5,  1.0,  0.30)
        ac_day  = _gaussian(h, 14.0, 3.0,  0.35)
        evening = _gaussian(h, 19.5, 1.6,  0.75)
        ev_chrg = _gaussian(h, 22.5, 1.5,  0.30)
        p.append(round(min(base + pump + morning + ac_day + evening + ev_chrg, 1.0), 4))
    return p

def _dom_3p_10kva_profile():
    """Three-phase up to 10 kVA: large home, multiple ACs."""
    p = []
    for i in range(96):
        h = i / 4.0
        base    = 0.16
        pump    = _gaussian(h, 6.0,  0.6,  0.50)
        morning = _gaussian(h, 8.0,  1.0,  0.25)
        ac_day  = _gaussian(h, 14.5, 3.0,  0.40)
        evening = _gaussian(h, 19.5, 1.5,  0.78)
        ev      = _gaussian(h, 22.0, 1.5,  0.25)
        p.append(round(min(base + pump + morning + ac_day + evening + ev, 1.0), 4))
    return p

def _dom_3p_25kva_profile():
    """10–25 kVA: affluent home with elevator, central AC, EV."""
    p = []
    for i in range(96):
        h = i / 4.0
        base    = 0.20
        pump    = _gaussian(h, 6.0,  0.6,  0.45)
        morning = _gaussian(h, 8.0,  1.2,  0.28)
        elev    = _gaussian(h, 9.5,  0.4,  0.10)
        ac_day  = _gaussian(h, 14.0, 3.5,  0.48)
        evening = _gaussian(h, 19.5, 1.6,  0.72)
        ev      = _gaussian(h, 23.0, 2.0,  0.35)
        p.append(round(min(base + pump + morning + elev + ac_day + evening + ev, 1.0), 4))
    return p

def _dom_3p_25kva_plus_profile():
    """Above 25 kVA: mansion / apartment complex owner."""
    p = []
    for i in range(96):
        h = i / 4.0
        base    = 0.22
        pump    = _gaussian(h, 6.0,  0.8,  0.40)
        morning = _gaussian(h, 8.0,  1.5,  0.30)
        midday  = _gaussian(h, 12.5, 2.5,  0.35)
        evening = _gaussian(h, 19.0, 2.0,  0.68)
        night   = _gaussian(h, 23.0, 2.0,  0.38)
        p.append(round(min(base + pump + morning + midday + evening + night, 1.0), 4))
    return p

# ─── COMMERCIAL PROFILES ──────────────────────────────────────────────────────

def _com_lv_1p_profile():
    """Small shop / clinic / salon: open 9:30 AM – 9 PM."""
    p = []
    for i in range(96):
        h = i / 4.0
        base     = 0.05
        open_r   = 0.70 * (1 / (1 + math.exp(-(h - 9.5) * 6)))
        business = _gaussian(h, 14.5, 3.5, 0.25)
        eve_shop = _gaussian(h, 18.5, 1.5, 0.30)
        close_r  = -0.75 * (1 / (1 + math.exp(-(h - 21.0) * 5)))
        val = base + open_r + business + eve_shop + close_r
        p.append(round(max(0.05, min(val, 1.0)), 4))
    return p

def _com_lv_3p_profile():
    """Office / mid-hotel / restaurant."""
    p = []
    for i in range(96):
        h = i / 4.0
        base     = 0.07
        open_r   = 0.55 * (1 / (1 + math.exp(-(h - 9.5) * 5)))
        office   = _gaussian(h, 13.5, 3.0, 0.35)
        lunch    = _gaussian(h, 13.0, 0.8, 0.20)
        dinner   = _gaussian(h, 20.0, 1.5, 0.35)
        close_r  = -0.60 * (1 / (1 + math.exp(-(h - 22.0) * 4)))
        val = base + open_r + office + lunch + dinner + close_r
        p.append(round(max(0.07, min(val, 1.0)), 4))
    return p

def _com_mv_11kv_profile():
    """Large hotel / mall: 24/7 baseload."""
    p = []
    for i in range(96):
        h = i / 4.0
        base     = 0.45
        morning  = _gaussian(h, 8.5,  1.2, 0.18)
        business = _gaussian(h, 13.5, 4.0, 0.28)
        evening  = _gaussian(h, 19.5, 2.0, 0.20)
        p.append(round(min(base + morning + business + evening, 1.0), 4))
    return p

def _com_mv_33kv_profile():
    """Industrial: near-continuous with shift peaks."""
    p = []
    for i in range(96):
        h = i / 4.0
        base      = 0.55
        day_shift = _gaussian(h, 10.5, 4.0, 0.30)
        eve_shift = _gaussian(h, 20.0, 2.5, 0.18)
        p.append(round(min(base + day_shift + eve_shift, 1.0), 4))
    return p

# ─── PRE-BUILT PROFILE MAP ────────────────────────────────────────────────────

LOAD_PROFILES = {
    "DOM_SP_5A":         _dom_5a_profile(),
    "DOM_SP_15A":        _dom_15a_profile(),
    "DOM_SP_30A":        _dom_30a_profile(),
    "DOM_SP_60A":        _dom_60a_profile(),
    "DOM_3P_10KVA":      _dom_3p_10kva_profile(),
    "DOM_3P_25KVA":      _dom_3p_25kva_profile(),
    "DOM_3P_25KVA_PLUS": _dom_3p_25kva_plus_profile(),
    "COM_LV_1P":         _com_lv_1p_profile(),
    "COM_LV_3P":         _com_lv_3p_profile(),
    "COM_MV_11KV":       _com_mv_11kv_profile(),
    "COM_MV_33KV":       _com_mv_33kv_profile(),
}

SEASON_MULT = {
    1: (1.25, 1.05), 2: (1.20, 1.04), 3: (1.00, 1.04), 4: (0.95, 1.08),
    5: (1.05, 1.12), 6: (1.10, 1.15), 7: (0.90, 1.05), 8: (0.88, 1.04),
    9: (0.92, 1.18), 10: (1.05, 1.28), 11: (1.10, 1.08), 12: (1.20, 1.05),
}

WEEKDAY_MOD = {
    0: (0.90, 1.00), 1: (0.90, 1.00), 2: (0.90, 1.00), 3: (0.90, 1.00),
    4: (0.92, 0.95), 5: (1.18, 1.15), 6: (0.95, 1.02),
}

NOMINAL_V = {"1P": 230.0, "3P": 400.0, "MV_11KV": 11000.0, "MV_33KV": 33000.0}
NOMINAL_V_LN = {"3P": 230.0, "MV_11KV": 6351.0, "MV_33KV": 19053.0}
LV_PROB = {"off_peak": 0.02, "mid": 0.08, "peak": 0.22, "critical": 0.38}
PHASE_CURRENT_IMBALANCE = 0.28
PHASE_VOLTAGE_VARIATION = 4.0

ANOMALY = {
    "tamper_pct": 0.015,
    "tamper_bypass_range": (0.30, 0.75),
    "outage_prob_per_dtr_per_day": 0.04,
    "outage_duration_min": (15, 480),
    "comm_loss_prob": 0.008,
}
