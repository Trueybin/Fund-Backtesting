from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "fund_cache.db"
CACHE_TTL = timedelta(hours=24)


class NavCache:
    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = Path(database_path or os.getenv("FUND_CACHE_PATH", DEFAULT_CACHE_PATH))
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS nav_cache (
                    fund_code TEXT NOT NULL,
                    nav_date TEXT NOT NULL,
                    unit_nav REAL NOT NULL,
                    change_rate REAL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (fund_code, nav_date)
                );
                CREATE INDEX IF NOT EXISTS idx_nav_cache_fund_date
                    ON nav_cache (fund_code, nav_date);
                CREATE TABLE IF NOT EXISTS fund_meta (
                    fund_code TEXT PRIMARY KEY,
                    fund_name TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def is_fresh_and_covers(self, fund_code: str, start_date: date, end_date: date) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT MIN(nav_date) AS first_date, MAX(nav_date) AS last_date,
                       MAX(updated_at) AS last_updated
                FROM nav_cache WHERE fund_code = ?
                """,
                (fund_code,),
            ).fetchone()
        if not row or not row["first_date"] or not row["last_updated"]:
            return False
        updated_at = datetime.fromisoformat(row["last_updated"])
        # A full AkShare history fetch normally ends on the latest available NAV date,
        # which can be before a requested end date when it falls on a weekend/holiday.
        # Fresh data that reaches the requested start date is therefore sufficient;
        # get_navs() below still confirms that the requested range has actual NAV rows.
        return (
            date.fromisoformat(row["first_date"]) <= start_date
            and date.fromisoformat(row["last_date"]) >= start_date
            and datetime.now(timezone.utc) - updated_at <= CACHE_TTL
        )

    def get_navs(self, fund_code: str, start_date: date, end_date: date) -> pd.DataFrame:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT nav_date, unit_nav, change_rate
                FROM nav_cache
                WHERE fund_code = ? AND nav_date BETWEEN ? AND ?
                ORDER BY nav_date
                """,
                (fund_code, start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
        return pd.DataFrame(rows, columns=["nav_date", "unit_nav", "change_rate"])

    def put_navs(self, fund_code: str, navs: pd.DataFrame) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                fund_code,
                pd.Timestamp(row.nav_date).date().isoformat(),
                float(row.unit_nav),
                float(row.change_rate) if pd.notna(row.change_rate) else None,
                updated_at,
            )
            for row in navs.itertuples(index=False)
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO nav_cache (fund_code, nav_date, unit_nav, change_rate, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(fund_code, nav_date) DO UPDATE SET
                    unit_nav = excluded.unit_nav,
                    change_rate = excluded.change_rate,
                    updated_at = excluded.updated_at
                """,
                rows,
            )

    def get_fund_name(self, fund_code: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT fund_name FROM fund_meta WHERE fund_code = ?", (fund_code,)
            ).fetchone()
        return row["fund_name"] if row else None

    def put_fund_name(self, fund_code: str, fund_name: str | None) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO fund_meta (fund_code, fund_name, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(fund_code) DO UPDATE SET
                    fund_name = excluded.fund_name,
                    updated_at = excluded.updated_at
                """,
                (fund_code, fund_name, datetime.now(timezone.utc).isoformat()),
            )
