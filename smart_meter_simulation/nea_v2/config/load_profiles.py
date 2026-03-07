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
    """
    5A household: fan, LED lights, phone charger, small B&W or LED TV.
    Very low load. Evening peak from lights + TV.
    No geyser, no AC, no pump.
    """
    p = []
    for i in range(96):
        h = i / 4.0
        base   = 0.10                              # standby always
        morn   = _gaussian(h, 6.0,  0.5,  0.20)   # morning lights (5:30–7:00)
        eve    = _gaussian(h, 19.5, 1.5,  0.70)   # evening lights + TV peak
        p.append(round(min(base + morn + eve, 1.0), 4))
    return p

def _dom_15a_profile():
    """
    15A household: fridge, fan, lights, instant geyser (morning spike),
    small AC (summer), water pump (morning).
    Strong morning pump+geyser spike; big evening peak.
    """
    p = []
    for i in range(96):
        h = i / 4.0
        base   = 0.12
        pump   = _gaussian(h, 6.0,  0.60, 0.55)   # pump + geyser 5:30–7:00
        daytime= _gaussian(h, 13.0, 2.0,  0.12)   # fridge cycle + misc
        evening= _gaussian(h, 19.75,1.5,  0.80)   # cooking + TV + lights
        late   = _gaussian(h, 20.75,0.6,  0.18)   # dinner second cook
        p.append(round(min(base + pump + daytime + evening + late, 1.0), 4))
    return p

def _dom_30a_profile():
    """
    30A household: all of 15A + washing machine (morning),
    larger AC (summer afternoons), water pump.
    Washing machine creates distinct morning shoulder.
    """
    p = []
    for i in range(96):
        h = i / 4.0
        base   = 0.14
        pump   = _gaussian(h, 6.0,  0.50, 0.55)
        wash   = _gaussian(h, 8.5,  0.75, 0.35)   # washing machine 8–10 AM
        ac     = _gaussian(h, 14.5, 2.5,  0.25)   # afternoon AC
        evening= _gaussian(h, 19.5, 1.4,  0.82)
        late   = _gaussian(h, 21.0, 0.5,  0.15)
        p.append(round(min(base + pump + wash + ac + evening + late, 1.0), 4))
    return p

def _dom_60a_profile():
    """
    60A household: high-end bungalow. Multiple ACs, water pump, EV charger,
    home theatre, geyser, garden lighting. More spread load through day.
    EV charging overnight possible.
    """
    p = []
    for i in range(96):
        h = i / 4.0
        base    = 0.18
        pump    = _gaussian(h, 6.25, 0.60, 0.50)
        morning = _gaussian(h, 8.5,  1.0,  0.30)  # breakfast appliances
        ac_day  = _gaussian(h, 14.0, 3.0,  0.35)  # daytime multi-AC
        evening = _gaussian(h, 19.5, 1.6,  0.75)  # peak evening
        ev_chrg = _gaussian(h, 22.5, 1.5,  0.30)  # EV overnight charging
        p.append(round(min(base + pump + morning + ac_day + evening + ev_chrg, 1.0), 4))
    return p

def _dom_3p_10kva_profile():
    """
    Three-phase up to 10 kVA: large home, multiple split ACs,
    multi-storey pump, home office. Even larger AC contribution.
    """
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
    """10–25 kVA: affluent home with elevator, central AC, EV, solar inverter."""
    p = []
    for i in range(96):
        h = i / 4.0
        base    = 0.20
        pump    = _gaussian(h, 6.0,  0.6,  0.45)
        morning = _gaussian(h, 8.0,  1.2,  0.28)
        elev    = _gaussian(h, 9.5,  0.4,  0.10)  # elevator runs during day
        ac_day  = _gaussian(h, 14.0, 3.5,  0.48)
        evening = _gaussian(h, 19.5, 1.6,  0.72)
        ev      = _gaussian(h, 23.0, 2.0,  0.35)
        p.append(round(min(base + pump + morning + elev + ac_day + evening + ev, 1.0), 4))
    return p

def _dom_3p_25kva_plus_profile():
    """Above 25 kVA: mansion / apartment complex owner. Near-commercial profile."""
    p = []
    for i in range(96):
        h = i / 4.0
        base    = 0.22
        pump    = _gaussian(h, 6.0,  0.8,  0.40)
        morning = _gaussian(h, 8.0,  1.5,  0.30)
        midday  = _gaussian(h, 12.5, 2.5,  0.35)
        evening = _gaussian(h, 19.0, 2.0,  0.68)
        night   = _gaussian(h, 23.0, 2.0,  0.38)  # bulk EV + pumping
        p.append(round(min(base + pump + morning + midday + evening + night, 1.0), 4))
    return p

# ─── COMMERCIAL PROFILES ──────────────────────────────────────────────────────

def _com_lv_1p_profile():
    """
    Small shop / clinic / salon (Single Phase LV).
    Open 9:30 AM – 9 PM. Sharp on/off.
    Lunch slight dip. Evening shopping peak.
    Sunday same as weekday in Nepal (Saturday off only).
    """
    p = []
    for i in range(96):
        h = i / 4.0
        base     = 0.05   # security light
        open_r   = 0.70 * (1 / (1 + math.exp(-(h - 9.5) * 6)))
        business = _gaussian(h, 14.5, 3.5, 0.25)
        eve_shop = _gaussian(h, 18.5, 1.5, 0.30)
        close_r  = -0.75 * (1 / (1 + math.exp(-(h - 21.0) * 5)))
        val = base + open_r + business + eve_shop + close_r
        p.append(round(max(0.05, min(val, 1.0)), 4))
    return p

def _com_lv_3p_profile():
    """
    Office / mid-hotel / restaurant (Three Phase LV).
    Office character: sharp open at 9:30, lunch dip, close 6 PM.
    Restaurant overlay: lunch peak 12–2, dinner peak 7–10 PM.
    """
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
    """
    Large hotel / mall / corporate tower (MV 11kV).
    Runs 24/7 — significant baseload (HVAC, lifts, data centre floor).
    Check-in/checkout spikes for hotel. Mall: 10AM–9PM retail.
    """
    p = []
    for i in range(96):
        h = i / 4.0
        base     = 0.45   # 24h HVAC + common area + server room
        morning  = _gaussian(h, 8.5,  1.2, 0.18)  # checkout rush
        business = _gaussian(h, 13.5, 4.0, 0.28)  # peak operations
        evening  = _gaussian(h, 19.5, 2.0, 0.20)  # dinner + check-in rush
        p.append(round(min(base + morning + business + evening, 1.0), 4))
    return p

def _com_mv_33kv_profile():
    """
    Industrial / large complex (MV 33kV).
    Runs near-continuously with shift-change peaks.
    Night shift baseload ~55% of peak.
    """
    p = []
    for i in range(96):
        h = i / 4.0
        base      = 0.55   # continuous process / shift base
        day_shift = _gaussian(h, 10.5, 4.0, 0.30)  # day shift operations
        eve_shift = _gaussian(h, 20.0, 2.5, 0.18)  # evening shift
        p.append(round(min(base + day_shift + eve_shift, 1.0), 4))
    return p

# ─── PRE-BUILT PROFILE MAP ────────────────────────────────────────────────────

LOAD_PROFILES = {
    # Domestic
    "DOM_SP_5A":         _dom_5a_profile(),
    "DOM_SP_15A":        _dom_15a_profile(),
    "DOM_SP_30A":        _dom_30a_profile(),
    "DOM_SP_60A":        _dom_60a_profile(),
    "DOM_3P_10KVA":      _dom_3p_10kva_profile(),
    "DOM_3P_25KVA":      _dom_3p_25kva_profile(),
    "DOM_3P_25KVA_PLUS": _dom_3p_25kva_plus_profile(),
    # Commercial
    "COM_LV_1P":         _com_lv_1p_profile(),
    "COM_LV_3P":         _com_lv_3p_profile(),
    "COM_MV_11KV":       _com_mv_11kv_profile(),
    "COM_MV_33KV":       _com_mv_33kv_profile(),
}

# ─── SEASONAL MULTIPLIERS ─────────────────────────────────────────────────────
# month → (domestic_mult, commercial_mult)
SEASON_MULT = {
    1:  (1.25, 1.05),   # Magh      — winter heating, geyser
    2:  (1.20, 1.04),   # Falgun    — late winter
    3:  (1.00, 1.04),   # Chaitra   — spring
    4:  (0.95, 1.08),   # Baisakh   — rising heat, New Year
    5:  (1.05, 1.12),   # Jestha    — pre-monsoon, coolers
    6:  (1.10, 1.15),   # Ashadh    — peak heat, heavy AC
    7:  (0.90, 1.05),   # Shrawan   — monsoon, cooler
    8:  (0.88, 1.04),   # Bhadra    — deep monsoon
    9:  (0.92, 1.18),   # Ashwin    — Dashain (Oct)
    10: (1.05, 1.28),   # Kartik    — Tihar festival lights
    11: (1.10, 1.08),   # Mangsir   — early winter
    12: (1.20, 1.05),   # Poush     — winter
}

# ─── WEEKDAY MODIFIERS ─────────────────────────────────────────────────────────
# Python weekday(): 0=Mon…4=Fri, 5=Sat, 6=Sun
# Nepal: Saturday = holiday; Sunday = first work day
WEEKDAY_MOD = {
    # (domestic, commercial)
    0: (0.90, 1.00),   # Monday
    1: (0.90, 1.00),   # Tuesday
    2: (0.90, 1.00),   # Wednesday
    3: (0.90, 1.00),   # Thursday
    4: (0.92, 0.95),   # Friday (half day govt, slight commercial dip)
    5: (1.18, 1.15),   # Saturday — HOLIDAY, everyone home + shopping
    6: (0.95, 1.02),   # Sunday — first work day Nepal
}

# ─── VOLTAGE PARAMETERS ───────────────────────────────────────────────────────
NOMINAL_V = {"1P": 230.0, "3P": 400.0, "MV_11KV": 11000.0, "MV_33KV": 33000.0}
# Phase-to-neutral for 3P (V_LL / √3 ≈ 231V for 400V system)
NOMINAL_V_LN = {"3P": 230.0, "MV_11KV": 6351.0, "MV_33KV": 19053.0}

# Low voltage probability by load tier (residential evening peak notorious in KTM)
LV_PROB = {"off_peak": 0.02, "mid": 0.08, "peak": 0.22, "critical": 0.38}

# Per-phase imbalance for advanced 3P metering (realistic load unbalance)
# Current: each phase gets share in [1 - IMBALANCE, 1 + IMBALANCE] of balanced 1/3
PHASE_CURRENT_IMBALANCE = 0.28   # ±28% — domestic/commercial often uneven
# Voltage: phase-to-phase variation (V) around nominal
PHASE_VOLTAGE_VARIATION = 4.0    # ±4V between phases typical on LV

# ─── ANOMALY CONFIG ───────────────────────────────────────────────────────────
ANOMALY = {
    "tamper_pct":            0.015,   # 1.5% of meters tampered
    "tamper_bypass_range":   (0.30, 0.75),
    "outage_prob_per_dtr_per_day": 0.04,
    "outage_duration_min":   (15, 480),
    "comm_loss_prob":        0.008,
}
