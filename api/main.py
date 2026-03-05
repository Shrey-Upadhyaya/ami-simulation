"""
FastAPI REST API - HES (Head-End System) Simulation for AMI Platform.

Provides REST endpoints for:
- Customer/meter lookup
- Billing data
- Daily/aggregate readings
- Meter events
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import date, timedelta
from typing import List, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Query

from config import POSTGRES_URL

app = FastAPI(
    title="AMI HES Simulation API",
    description="REST API simulating a Head-End System for smart metering",
    version="1.0.0",
)


def get_db():
    conn = psycopg2.connect(POSTGRES_URL, cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


@app.get("/")
def root():
    return {"service": "AMI HES API", "status": "running"}


@app.get("/api/customers")
def list_customers(limit: int = Query(50, ge=1, le=200)):
    """List customers with their meter IDs."""
    with psycopg2.connect(POSTGRES_URL, cursor_factory=RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, meter_id, customer_name, address, tariff_id, created_at FROM customers ORDER BY id LIMIT %s",
                (limit,),
            )
            return cur.fetchall()


@app.get("/api/customers/{meter_id}")
def get_customer(meter_id: str):
    """Get customer details by meter ID."""
    with psycopg2.connect(POSTGRES_URL, cursor_factory=RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT c.*, t.name as tariff_name, t.rate_per_kwh FROM customers c LEFT JOIN tariffs t ON c.tariff_id = t.id WHERE c.meter_id = %s",
                (meter_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, f"Customer not found: {meter_id}")
            return dict(row)


@app.get("/api/meters/{meter_id}/readings")
def get_meter_readings(
    meter_id: str,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = Query(90, ge=1, le=365),
):
    """Get daily aggregate readings for a meter (from PostgreSQL)."""
    from_date = from_date or date.today() - timedelta(days=limit)
    to_date = to_date or date.today()
    with psycopg2.connect(POSTGRES_URL, cursor_factory=RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT reading_date, total_kwh, peak_kwh, off_peak_kwh, created_at
                FROM daily_readings
                WHERE meter_id = %s AND reading_date BETWEEN %s AND %s
                ORDER BY reading_date DESC
                """,
                (meter_id, from_date, to_date),
            )
            return cur.fetchall()


@app.get("/api/meters/{meter_id}/billing")
def get_meter_billing(
    meter_id: str,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
):
    """Get billing summary for a meter over a date range."""
    from_date = from_date or date.today().replace(day=1)
    to_date = to_date or date.today()
    with psycopg2.connect(POSTGRES_URL, cursor_factory=RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT SUM(dr.total_kwh) as total_kwh, c.tariff_id, t.rate_per_kwh,
                       SUM(dr.total_kwh) * t.rate_per_kwh as amount_due
                FROM daily_readings dr
                JOIN customers c ON c.meter_id = dr.meter_id
                JOIN tariffs t ON t.id = c.tariff_id
                WHERE dr.meter_id = %s AND dr.reading_date BETWEEN %s AND %s
                GROUP BY c.tariff_id, t.rate_per_kwh
                """,
                (meter_id, from_date, to_date),
            )
            row = cur.fetchone()
            if not row:
                return {"meter_id": meter_id, "total_kwh": 0, "amount_due": 0, "period": [str(from_date), str(to_date)]}
            return dict(row) | {"meter_id": meter_id, "period": [str(from_date), str(to_date)]}


@app.get("/api/tariffs")
def list_tariffs():
    """List available tariffs."""
    with psycopg2.connect(POSTGRES_URL, cursor_factory=RealDictCursor) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tariffs ORDER BY id")
            return cur.fetchall()


@app.get("/api/health")
def health():
    """Health check (DB connectivity)."""
    try:
        with psycopg2.connect(POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(503, str(e))

