from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "lotto.db"


def _configure_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA cache_size = -20000")
    return conn


def ensure_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _configure_connection(sqlite3.connect(DB_PATH)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lotto_draws (
                issue TEXT PRIMARY KEY,
                draw_date TEXT NOT NULL,
                front_numbers TEXT NOT NULL,
                back_numbers TEXT NOT NULL,
                raw_result TEXT,
                pool_balance_afterdraw TEXT,
                prize_level_list TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sync_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_schemes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_issue TEXT NOT NULL,
                seed_mode TEXT NOT NULL,
                seed_value TEXT NOT NULL,
                moving_line INTEGER NOT NULL,
                ai_engine TEXT NOT NULL,
                label TEXT NOT NULL,
                confidence REAL NOT NULL,
                strategy TEXT NOT NULL,
                front_numbers TEXT NOT NULL,
                back_numbers TEXT NOT NULL,
                rationale TEXT NOT NULL,
                multiple INTEGER NOT NULL DEFAULT 1,
                is_additional INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(target_issue, front_numbers, back_numbers)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manual_draw_results (
                issue TEXT PRIMARY KEY,
                draw_date TEXT,
                front_numbers TEXT NOT NULL,
                back_numbers TEXT NOT NULL,
                high_pool INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS divination_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_issue TEXT,
                seed_mode TEXT NOT NULL,
                seed_value TEXT NOT NULL,
                divination_datetime TEXT NOT NULL,
                target_draw_datetime TEXT NOT NULL,
                requested_scheme_count INTEGER NOT NULL DEFAULT 0,
                visible_scheme_count INTEGER NOT NULL DEFAULT 0,
                requested_strategy_mode TEXT NOT NULL,
                effective_strategy_mode TEXT NOT NULL,
                moving_line INTEGER NOT NULL,
                ai_engine TEXT NOT NULL,
                ai_enabled INTEGER NOT NULL DEFAULT 0,
                tuning_profile TEXT,
                issue_confidence REAL,
                calibrated_confidence REAL,
                applied_threshold REAL,
                should_observe INTEGER NOT NULL DEFAULT 0,
                front_confidence REAL,
                front_calibrated_confidence REAL,
                front_gate REAL,
                back_confidence REAL,
                back_calibrated_confidence REAL,
                back_gate REAL,
                count_policy TEXT,
                decision_tier TEXT,
                deep_search_triggered INTEGER NOT NULL DEFAULT 0,
                deep_search_reason TEXT,
                decision_reason TEXT,
                summary_explanation TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS divination_run_schemes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                scheme_index INTEGER NOT NULL,
                label TEXT NOT NULL,
                confidence REAL NOT NULL,
                strategy TEXT NOT NULL,
                front_numbers TEXT NOT NULL,
                back_numbers TEXT NOT NULL,
                rationale TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(run_id, scheme_index),
                FOREIGN KEY(run_id) REFERENCES divination_runs(id) ON DELETE CASCADE
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(lotto_draws)").fetchall()}
        if "prize_level_list" not in columns:
            conn.execute("ALTER TABLE lotto_draws ADD COLUMN prize_level_list TEXT")
        saved_scheme_columns = {row[1] for row in conn.execute("PRAGMA table_info(saved_schemes)").fetchall()}
        saved_scheme_migrations = {
            "tuning_profile": "TEXT",
            "issue_confidence": "REAL",
            "calibrated_confidence": "REAL",
            "applied_threshold": "REAL",
            "should_observe": "INTEGER NOT NULL DEFAULT 0",
            "front_confidence": "REAL",
            "front_gate": "REAL",
            "back_confidence": "REAL",
            "back_gate": "REAL",
            "deep_search_triggered": "INTEGER NOT NULL DEFAULT 0",
            "deep_search_reason": "TEXT",
            "decision_reason": "TEXT",
            "multiple": "INTEGER NOT NULL DEFAULT 1",
            "is_additional": "INTEGER NOT NULL DEFAULT 0",
        }
        for column_name, column_type in saved_scheme_migrations.items():
            if column_name not in saved_scheme_columns:
                conn.execute(f"ALTER TABLE saved_schemes ADD COLUMN {column_name} {column_type}")
        manual_draw_columns = {row[1] for row in conn.execute("PRAGMA table_info(manual_draw_results)").fetchall()}
        if "high_pool" not in manual_draw_columns:
            conn.execute("ALTER TABLE manual_draw_results ADD COLUMN high_pool INTEGER NOT NULL DEFAULT 0")
        divination_run_columns = {row[1] for row in conn.execute("PRAGMA table_info(divination_runs)").fetchall()}
        divination_run_migrations = {
            "target_issue": "TEXT",
            "requested_scheme_count": "INTEGER NOT NULL DEFAULT 0",
            "visible_scheme_count": "INTEGER NOT NULL DEFAULT 0",
            "requested_strategy_mode": "TEXT NOT NULL DEFAULT 'smart_balance'",
            "effective_strategy_mode": "TEXT NOT NULL DEFAULT 'smart_balance'",
            "ai_enabled": "INTEGER NOT NULL DEFAULT 0",
            "tuning_profile": "TEXT",
            "issue_confidence": "REAL",
            "calibrated_confidence": "REAL",
            "applied_threshold": "REAL",
            "should_observe": "INTEGER NOT NULL DEFAULT 0",
            "front_confidence": "REAL",
            "front_calibrated_confidence": "REAL",
            "front_gate": "REAL",
            "back_confidence": "REAL",
            "back_calibrated_confidence": "REAL",
            "back_gate": "REAL",
            "count_policy": "TEXT",
            "decision_tier": "TEXT",
            "deep_search_triggered": "INTEGER NOT NULL DEFAULT 0",
            "deep_search_reason": "TEXT",
            "decision_reason": "TEXT",
            "summary_explanation": "TEXT",
        }
        for column_name, column_type in divination_run_migrations.items():
            if column_name not in divination_run_columns:
                conn.execute(f"ALTER TABLE divination_runs ADD COLUMN {column_name} {column_type}")
        conn.commit()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    ensure_database()
    conn = _configure_connection(sqlite3.connect(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
