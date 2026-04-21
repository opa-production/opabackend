"""
Migration 005 — Add missing indexes for high-traffic query paths.

cars:  verification_status, is_hidden, created_at — used on every explore/my-cars query
bookings: status, (car_id, status) — used on dashboard aggregation and availability subqueries
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.migrations.runner import migration


@migration("m005_perf_indexes")
async def m005_perf_indexes(engine: AsyncEngine) -> None:
    indexes = [
        # Cars listing filters — hit on every explore page load
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cars_verification_status ON cars(verification_status)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cars_is_hidden ON cars(is_hidden)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cars_created_at ON cars(created_at DESC)",
        # Composite: covers the explore WHERE + ORDER BY in one index scan
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_cars_explore ON cars(verification_status, is_hidden, created_at DESC)",
        # Bookings status — used in dashboard SUM/COUNT and availability subqueries
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_bookings_status ON bookings(status)",
        # Composite: covers the availability subquery (car_id + status filter)
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_bookings_car_status ON bookings(car_id, status)",
    ]
    # CONCURRENTLY cannot run inside a transaction block
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        for ddl in indexes:
            await conn.execute(text(ddl))
