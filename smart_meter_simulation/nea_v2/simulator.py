"""
NEA Smart Meter Simulator v2
=============================
Fixed topology: 1 substation · 10 feeders · 100 meters/feeder
Consumer types: Domestic (DOM) + Commercial (COM)
All data routed to DCS_BALAJU_01

Usage:
  python simulator.py --mode batch --days 7
  python simulator.py --mode stream --speed 60
  python simulator.py --mode both --days 30
"""

import os, sys, csv, json, time, argparse, datetime, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.infrastructure import build_infrastructure
from core.generator       import generate_reading

NPT = datetime.timezone(datetime.timedelta(hours=5, minutes=45))
OUT = os.path.join(os.path.dirname(__file__), "output")

# ─── Outage manager (unchanged from v1) ──────────────────────────────────────
class OutageManager:
    def __init__(self, dtr_ids):
        self.dtr_ids       = dtr_ids
        self.active        = {}   # dtr_id → {end_time, type}
        self.log           = []
        self._prob_per_slot = 0.04 / 96

    def tick(self, dt):
        expired = [d for d, v in self.active.items() if v["end_time"] <= dt]
        for d in expired:
            del self.active[d]
            self.log.append({"event":"RESTORED","dtr_id":d,"time":str(dt)})
        for dtr in self.dtr_ids:
            if dtr not in self.active and random.random() < self._prob_per_slot:
                dur  = random.randint(15, 480)
                kind = random.choice(["CABLE_FAULT","TREE_CONTACT","FUSE_BLOW",
                                      "DTR_FAILURE","ANIMAL_CONTACT"])
                self.active[dtr] = {
                    "end_time": dt + datetime.timedelta(minutes=dur),
                    "type": kind, "dur_min": dur
                }
                self.log.append({"event":"OUTAGE","dtr_id":dtr,"type":kind,
                                 "start":str(dt),"dur_min":dur})
        return {d: v["type"] for d, v in self.active.items()}

    def summary(self):
        starts = [e for e in self.log if e["event"]=="OUTAGE"]
        return {
            "total_events":       len(starts),
            "total_dtr_minutes":  sum(e["dur_min"] for e in starts),
            "avg_duration_min":   round(sum(e["dur_min"] for e in starts)/max(1,len(starts)),1),
            "affected_dtrs":      len(set(e["dtr_id"] for e in starts)),
        }

# ─── BATCH ────────────────────────────────────────────────────────────────────
def run_batch(meters, dtrs, days=7):
    batch_dir = os.path.join(OUT, "batch")
    os.makedirs(batch_dir, exist_ok=True)
    os.makedirs(os.path.join(OUT), exist_ok=True)

    dtr_ids    = [d["dtr_id"] for d in dtrs]
    outage_mgr = OutageManager(dtr_ids)
    cum_reg    = {m["meter_id"]: m["register_start_kwh"] for m in meters}

    start = (datetime.datetime.now(NPT) - datetime.timedelta(days=days))\
              .replace(hour=0, minute=0, second=0, microsecond=0)

    total = 0
    print(f"\n📊 Batch simulation: {start.date()} → +{days} days  |  {len(meters)} meters")
    print(f"   Expected: {len(meters)*96*days:,} readings\n")

    for day_n in range(days):
        day_dt   = start + datetime.timedelta(days=day_n)
        day_str  = day_dt.strftime("%Y-%m-%d")
        day_file = os.path.join(batch_dir, f"nea_readings_{day_str}.csv")
        day_count = 0

        with open(day_file, "w", newline="", encoding="utf-8") as f:
            writer = None
            for slot in range(96):
                slot_dt  = day_dt + datetime.timedelta(minutes=slot * 15)
                outages  = outage_mgr.tick(slot_dt)

                for m in meters:
                    is_out   = m["dtr_id"] in outages
                    out_type = outages.get(m["dtr_id"])
                    rec = generate_reading(m, slot_dt, is_out, out_type)

                    delta = rec["import_kwh"] or 0.0
                    cum_reg[m["meter_id"]] += delta
                    rec["cumulative_kwh"] = round(cum_reg[m["meter_id"]], 2)

                    if writer is None:
                        writer = csv.DictWriter(f, fieldnames=rec.keys())
                        writer.writeheader()
                    writer.writerow(rec)
                    day_count += 1

        total += day_count
        bar = "█" * (day_n+1) + "░" * (days-day_n-1)
        print(f"  [{bar}] {day_str}  {day_count:,} readings")

    # ── Write registry ────────────────────────────────────────────────────────
    registry_path = os.path.join(OUT, "meter_registry.csv")
    with open(registry_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=meters[0].keys())
        w.writeheader(); w.writerows(meters)

    dtr_path = os.path.join(OUT, "dtr_registry.csv")
    with open(dtr_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=dtrs[0].keys())
        w.writeheader(); w.writerows(dtrs)

    summary = {
        "simulation_type":    "BATCH",
        "generated_npt":      datetime.datetime.now(NPT).strftime("%Y-%m-%d %H:%M:%S NPT"),
        "start_date":         str(start.date()),
        "days":               days,
        "total_meters":       len(meters),
        "total_readings":     total,
        "total_dtrs":         len(dtrs),
        "outage_summary":     outage_mgr.summary(),
        "consumer_mix":       _count(meters,"consumer_category"),
        "subtype_mix":        _count(meters,"consumer_subtype"),
        "phase_mix":          _count(meters,"phase"),
        "tariff_mix":         _count(meters,"tariff_code"),
        "tampered_meters":    sum(1 for m in meters if m["is_tampered"]),
    }
    with open(os.path.join(OUT,"simulation_summary.json"),"w") as f:
        json.dump(summary, f, indent=2)
    with open(os.path.join(OUT,"outage_log.json"),"w") as f:
        json.dump({"summary":outage_mgr.summary(),"events":outage_mgr.log},f,indent=2)

    print(f"\n✅ Batch done — {total:,} readings | registry: {registry_path}")
    return summary

# ─── STREAM ───────────────────────────────────────────────────────────────────
def run_stream(meters, dtrs, speed=60.0, duration=None):
    dtr_ids    = [d["dtr_id"] for d in dtrs]
    outage_mgr = OutageManager(dtr_ids)
    cum_reg    = {m["meter_id"]: m["register_start_kwh"] for m in meters}

    now = datetime.datetime.now(NPT)
    dt  = now.replace(second=0, microsecond=0)
    dt -= datetime.timedelta(minutes=dt.minute % 15)

    sleep_s  = (15 * 60) / speed
    start_ts = time.time()
    tick     = 0

    stream_path = os.path.join(OUT, "stream", "stream_output.jsonl")
    os.makedirs(os.path.dirname(stream_path), exist_ok=True)

    print(f"\n🔴 LIVE STREAM — {len(meters)} meters — speed {speed}x — "
          f"sleep {sleep_s:.2f}s/tick")

    with open(stream_path, "a", encoding="utf-8") as sf:
        while True:
            t0      = time.time()
            outages = outage_mgr.tick(dt)
            batch   = []
            for m in meters:
                is_out   = m["dtr_id"] in outages
                out_type = outages.get(m["dtr_id"])
                rec = generate_reading(m, dt, is_out, out_type)
                cum_reg[m["meter_id"]] += (rec["import_kwh"] or 0)
                rec["cumulative_kwh"] = round(cum_reg[m["meter_id"]], 2)
                batch.append(rec)
                sf.write(json.dumps(rec) + "\n")
            sf.flush()

            active   = sum(1 for r in batch if not r["is_outage"])
            total_kw = sum(r["active_power_kw"] or 0 for r in batch)
            v_evts   = sum(1 for r in batch if r["is_voltage_event"])
            print(f"  ⚡ [{dt.strftime('%H:%M NPT')}] "
                  f"Active:{active}/{len(meters)}  "
                  f"Load:{total_kw:.1f}kW  "
                  f"VEvents:{v_evts}  "
                  f"Outages:{len(outages)}DTRs", flush=True)

            tick += 1
            dt   += datetime.timedelta(minutes=15)
            if duration and (time.time() - start_ts) >= duration:
                print(f"\n✅ Stream ended — {tick} ticks"); break
            elapsed = time.time() - t0
            if (wait := sleep_s - elapsed) > 0:
                time.sleep(wait)

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def _count(items, key):
    from collections import Counter
    return dict(Counter(i[key] for i in items))

def _banner():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║  NEA Smart Meter Simulator v2                                ║
║  1 Substation · 10 Feeders · 100 Meters/Feeder               ║
║  Consumer types: Domestic (DOM) + Commercial (COM)           ║
║  Data sink: DCS_BALAJU_01 (Balaju Primary Substation)        ║
╚═══════════════════════════════════════════════════════════════╝""")

# ─── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mode",    choices=["batch","stream","both"], default="batch")
    p.add_argument("--days",    type=int,   default=7)
    p.add_argument("--speed",   type=float, default=60.0)
    p.add_argument("--seed",    type=int,   default=42)
    p.add_argument("--duration",type=int,   default=None)
    args = p.parse_args()

    _banner()
    meters, dtrs, dcus = build_infrastructure(seed=args.seed)

    if args.mode in ("batch","both"):
        run_batch(meters, dtrs, days=args.days)
    if args.mode in ("stream","both"):
        run_stream(meters, dtrs, speed=args.speed, duration=args.duration)
