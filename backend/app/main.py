
import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from contextlib import asynccontextmanager

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field
from typing import Literal

from app.database import pool


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=LOG_FORMAT,
)

logger = logging.getLogger("taxi-api")

log_dir = Path("/app/logs")
log_dir.mkdir(parents=True, exist_ok=True)

file_handler = RotatingFileHandler(
    log_dir / "taxi-backend.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
logger.addHandler(file_handler)

logger.info("taxi_backend_logging_initialized")


REQUEST_COUNT = Counter(
    "taxi_http_requests_total",
    "HTTP requests handled by the Taxi API",
    ["method", "path", "status"],
)
REQUEST_DURATION = Histogram(
    "taxi_http_request_duration_seconds",
    "HTTP request duration in seconds",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()
    yield
    pool.close()

app = FastAPI(
    title="Taxi Booking API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)

@app.middleware("http")
async def collect_metrics(request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        REQUEST_COUNT.labels(
            request.method, request.url.path, str(status)
        ).inc()
        REQUEST_DURATION.observe(time.perf_counter() - start)

class CustomerIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    email: str | None = Field(default=None, max_length=255)

class DriverIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    license_plate: str = Field(min_length=3, max_length=20)

class TripIn(BaseModel):
    customer_id: int = Field(gt=0)
    pickup_address: str = Field(min_length=2, max_length=255)
    destination_address: str = Field(min_length=2, max_length=255)
    fare: float = Field(ge=0, le=100000000)

class TripStatusIn(BaseModel):
    status: Literal[
        "assigned", "in_progress", "completed", "cancelled"
    ]

@app.get("/api/health")
def health():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "database": "connected"}

@app.get("/api/customers")
def list_customers():
    with pool.connection() as conn:
        return conn.execute(
            "SELECT * FROM customers ORDER BY id DESC"
        ).fetchall()

@app.post("/api/customers", status_code=201)
def create_customer(data: CustomerIn):
    try:
        with pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO customers (full_name, phone, email)
                VALUES (%s, %s, %s)
                RETURNING *
                """,
                (data.full_name, data.phone, data.email),
            ).fetchone()
        logger.info("customer_created customer_id=%s", row["id"])
        return row
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "Phone or email already exists")

@app.get("/api/drivers")
def list_drivers():
    with pool.connection() as conn:
        return conn.execute(
            "SELECT * FROM drivers ORDER BY id DESC"
        ).fetchall()

@app.post("/api/drivers", status_code=201)
def create_driver(data: DriverIn):
    try:
        with pool.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO drivers (full_name, phone, license_plate)
                VALUES (%s, %s, %s)
                RETURNING *
                """,
                (data.full_name, data.phone, data.license_plate),
            ).fetchone()
        logger.info("driver_created driver_id=%s", row["id"])
        return row
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "Phone or license plate already exists")

@app.get("/api/trips")
def list_trips():
    with pool.connection() as conn:
        return conn.execute(
            """
            SELECT t.*, c.full_name AS customer_name,
                   d.full_name AS driver_name
            FROM trips t
            JOIN customers c ON c.id = t.customer_id
            LEFT JOIN drivers d ON d.id = t.driver_id
            ORDER BY t.id DESC
            """
        ).fetchall()

@app.post("/api/trips", status_code=201)
def create_trip(data: TripIn):
    with pool.connection() as conn:
        customer = conn.execute(
            "SELECT id FROM customers WHERE id = %s",
            (data.customer_id,),
        ).fetchone()
        if not customer:
            raise HTTPException(404, "Customer not found")

        row = conn.execute(
            """
            INSERT INTO trips (
                customer_id, pickup_address,
                destination_address, fare
            )
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (
                data.customer_id,
                data.pickup_address,
                data.destination_address,
                data.fare,
            ),
        ).fetchone()

    logger.info("trip_created trip_id=%s", row["id"])
    return row

@app.patch("/api/trips/{trip_id}/status")
def update_trip_status(trip_id: int, data: TripStatusIn):
    allowed_transitions = {
        "pending": {"assigned", "cancelled"},
        "assigned": {"in_progress", "cancelled"},
        "in_progress": {"completed", "cancelled"},
        "completed": set(),
        "cancelled": set(),
    }

    with pool.connection() as conn:
        with conn.transaction():
            trip = conn.execute(
                "SELECT * FROM trips WHERE id = %s FOR UPDATE",
                (trip_id,),
            ).fetchone()

            if not trip:
                raise HTTPException(404, "Trip not found")

            current = trip["status"]
            if data.status not in allowed_transitions[current]:
                raise HTTPException(
                    409,
                    f"Cannot change trip status from {current} to {data.status}",
                )

            driver_id = trip["driver_id"]

            if data.status == "assigned":
                driver = conn.execute(
                    """
                    SELECT id FROM drivers
                    WHERE is_available = TRUE
                    ORDER BY id
                    LIMIT 1
                    FOR UPDATE
                    """
                ).fetchone()

                if not driver:
                    raise HTTPException(409, "No available driver")

                driver_id = driver["id"]
                conn.execute(
                    "UPDATE drivers SET is_available = FALSE WHERE id = %s",
                    (driver_id,),
                )

            if data.status == "completed" and driver_id is not None:
                conn.execute(
                    "UPDATE drivers SET is_available = TRUE WHERE id = %s",
                    (driver_id,),
                )

            if data.status == "cancelled" and driver_id is not None:
                conn.execute(
                    "UPDATE drivers SET is_available = TRUE WHERE id = %s",
                    (driver_id,),
                )

            completed_at = (
                "NOW()" if data.status == "completed" else None
            )

            if completed_at:
                row = conn.execute(
                    """
                    UPDATE trips
                    SET status = %s, driver_id = %s, completed_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (data.status, driver_id, trip_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    UPDATE trips
                    SET status = %s, driver_id = %s, completed_at = NULL
                    WHERE id = %s
                    RETURNING *
                    """,
                    (data.status, driver_id, trip_id),
                ).fetchone()

    logger.info(
        "trip_status_changed trip_id=%s status=%s",
        trip_id, data.status,
    )
    return row

@app.get("/metrics")
def metrics():
    return Response(
        generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
