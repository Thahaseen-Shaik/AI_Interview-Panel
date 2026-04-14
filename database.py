import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except Exception:
    psycopg2 = None
    RealDictCursor = None

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_NAME = os.getenv("DB_PATH", "interviews.db")


def _use_postgres():
    return (
        psycopg2 is not None
        and bool(DATABASE_URL)
        and DATABASE_URL.startswith(("postgres://", "postgresql://"))
    )


def _normalize_database_url():
    if not DATABASE_URL:
        return ""
    return DATABASE_URL.replace("postgres://", "postgresql://", 1)


def _connect():
    if _use_postgres():
        return psycopg2.connect(_normalize_database_url(), cursor_factory=RealDictCursor)

    db_path = Path(DB_NAME)
    if db_path.parent and str(db_path.parent) not in {".", ""}:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _query(sql):
    if _use_postgres():
        return sql.replace("?", "%s")
    return sql


def _table_columns(conn, table_name):
    if _use_postgres():
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s
            """,
            (table_name,),
        )
        rows = cursor.fetchall()
        return {row["column_name"] for row in rows}

    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _ensure_column(conn, table_name, column_name, column_type):
    if column_name not in _table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _execute_fetchone(conn, sql, params=()):
    if _use_postgres():
        cursor = conn.cursor()
        cursor.execute(_query(sql), params)
        return cursor.fetchone()
    return conn.execute(_query(sql), params).fetchone()


def _execute_fetchall(conn, sql, params=()):
    if _use_postgres():
        cursor = conn.cursor()
        cursor.execute(_query(sql), params)
        return cursor.fetchall()
    return conn.execute(_query(sql), params).fetchall()


def _execute(conn, sql, params=()):
    if _use_postgres():
        conn.cursor().execute(_query(sql), params)
    else:
        conn.execute(_query(sql), params)


def _commit(conn):
    conn.commit()


def _close(conn):
    conn.close()


def _timestamp():
    return datetime.utcnow().isoformat(timespec="seconds")


def init_db():
    conn = _connect()
    try:
        if _use_postgres():
            conn.cursor().execute(
                """
                CREATE TABLE IF NOT EXISTS admins (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.cursor().execute(
                """
                CREATE TABLE IF NOT EXISTS interviews (
                    id SERIAL PRIMARY KEY,
                    candidate_name TEXT NOT NULL,
                    candidate_email TEXT NOT NULL,
                    interview_time TEXT NOT NULL,
                    token TEXT UNIQUE NOT NULL,
                    status TEXT DEFAULT 'scheduled',
                    started_at TEXT,
                    completed_at TEXT,
                    duration_minutes REAL,
                    score INTEGER,
                    feedback TEXT,
                    transcript TEXT,
                    ai_context TEXT
                )
                """
            )
            conn.cursor().execute(
                """
                CREATE TABLE IF NOT EXISTS interview_messages (
                    id SERIAL PRIMARY KEY,
                    token TEXT NOT NULL,
                    speaker TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.cursor().execute(
                """
                CREATE TABLE IF NOT EXISTS compatibility_checks (
                    id SERIAL PRIMARY KEY,
                    token TEXT NOT NULL,
                    check_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.cursor().execute(
                """
                CREATE TABLE IF NOT EXISTS proctoring_events (
                    id SERIAL PRIMARY KEY,
                    token TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            _commit(conn)
            return

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_name TEXT NOT NULL,
                candidate_email TEXT NOT NULL,
                interview_time TEXT NOT NULL,
                token TEXT UNIQUE NOT NULL,
                status TEXT DEFAULT 'scheduled',
                started_at TEXT,
                completed_at TEXT,
                duration_minutes REAL,
                score INTEGER,
                feedback TEXT,
                transcript TEXT,
                ai_context TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS interview_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL,
                speaker TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS compatibility_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL,
                check_name TEXT NOT NULL,
                status TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS proctoring_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL,
                event_type TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        _ensure_column(conn, "interviews", "status", "TEXT DEFAULT 'scheduled'")
        _ensure_column(conn, "interviews", "started_at", "TEXT")
        _ensure_column(conn, "interviews", "completed_at", "TEXT")
        _ensure_column(conn, "interviews", "duration_minutes", "REAL")
        _ensure_column(conn, "interviews", "score", "INTEGER")
        _ensure_column(conn, "interviews", "feedback", "TEXT")
        _ensure_column(conn, "interviews", "transcript", "TEXT")
        _ensure_column(conn, "interviews", "ai_context", "TEXT")
        _commit(conn)
    finally:
        _close(conn)


def create_admin(username, password_hash):
    conn = _connect()
    try:
        if _use_postgres():
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO admins (username, password_hash, created_at)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (username, password_hash, _timestamp()),
            )
            admin_id = cursor.fetchone()["id"]
            _commit(conn)
            return admin_id

        cursor = conn.execute(
            """
            INSERT INTO admins (username, password_hash, created_at)
            VALUES (?, ?, ?)
            """,
            (username, password_hash, _timestamp()),
        )
        _commit(conn)
        return cursor.lastrowid
    finally:
        _close(conn)


def get_admin_by_username(username):
    conn = _connect()
    try:
        return _execute_fetchone(conn, "SELECT * FROM admins WHERE username = ?", (username,))
    finally:
        _close(conn)


def get_admin_by_id(admin_id):
    conn = _connect()
    try:
        return _execute_fetchone(conn, "SELECT * FROM admins WHERE id = ?", (admin_id,))
    finally:
        _close(conn)


def schedule_interview(name, email, interview_time):
    scheduled = schedule_interviews_bulk(
        [
            {
                "candidate_name": name,
                "candidate_email": email,
            }
        ],
        interview_time,
    )
    return scheduled[0]["token"]


def schedule_interviews_bulk(candidate_rows, interview_time):
    conn = _connect()
    scheduled = []

    try:
        for candidate in candidate_rows:
            token = str(uuid.uuid4())
            if _use_postgres():
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO interviews (
                        candidate_name, candidate_email, interview_time, token, status, ai_context
                    ) VALUES (%s, %s, %s, %s, 'scheduled', %s)
                    RETURNING id
                    """,
                    (
                        candidate["candidate_name"],
                        candidate["candidate_email"],
                        interview_time,
                        token,
                        "[]",
                    ),
                )
                interview_id = cursor.fetchone()["id"]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO interviews (
                        candidate_name, candidate_email, interview_time, token, status, ai_context
                    ) VALUES (?, ?, ?, ?, 'scheduled', ?)
                    """,
                    (
                        candidate["candidate_name"],
                        candidate["candidate_email"],
                        interview_time,
                        token,
                        "[]",
                    ),
                )
                interview_id = cursor.lastrowid

            scheduled.append(
                {
                    "id": interview_id,
                    "candidate_name": candidate["candidate_name"],
                    "candidate_email": candidate["candidate_email"],
                    "interview_time": interview_time,
                    "token": token,
                }
            )

        _commit(conn)
        return scheduled
    finally:
        _close(conn)


def get_interview_by_token(token):
    conn = _connect()
    try:
        return _execute_fetchone(conn, "SELECT * FROM interviews WHERE token = ?", (token,))
    finally:
        _close(conn)


def get_all_interviews():
    conn = _connect()
    try:
        return _execute_fetchall(conn, "SELECT * FROM interviews ORDER BY interview_time DESC, id DESC")
    finally:
        _close(conn)


def update_interview_started(token):
    conn = _connect()
    try:
        _execute(
            conn,
            """
            UPDATE interviews
            SET status = 'in_progress',
                started_at = COALESCE(started_at, ?)
            WHERE token = ? AND status != 'completed'
            """,
            (_timestamp(), token),
        )
        _commit(conn)
    finally:
        _close(conn)


def complete_interview(token, score, feedback, transcript, duration_minutes):
    conn = _connect()
    try:
        _execute(
            conn,
            """
            UPDATE interviews
            SET status = 'completed',
                completed_at = ?,
                duration_minutes = ?,
                score = ?,
                feedback = ?,
                transcript = ?
            WHERE token = ?
            """,
            (
                _timestamp(),
                duration_minutes,
                score,
                feedback,
                transcript,
                token,
            ),
        )
        _commit(conn)
    finally:
        _close(conn)


def get_interview_context(token):
    conn = _connect()
    try:
        row = _execute_fetchone(conn, "SELECT ai_context FROM interviews WHERE token = ?", (token,))
        if not row or not row["ai_context"]:
            return []
        try:
            parsed = json.loads(row["ai_context"])
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    finally:
        _close(conn)


def save_interview_context(token, context):
    conn = _connect()
    try:
        _execute(
            conn,
            """
            UPDATE interviews
            SET ai_context = ?
            WHERE token = ?
            """,
            (json.dumps(context, ensure_ascii=False), token),
        )
        _commit(conn)
    finally:
        _close(conn)


def save_interview_message(token, speaker, content):
    conn = _connect()
    try:
        _execute(
            conn,
            """
            INSERT INTO interview_messages (token, speaker, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, speaker, content, _timestamp()),
        )
        _commit(conn)
    finally:
        _close(conn)


def get_interview_messages(token):
    conn = _connect()
    try:
        return _execute_fetchall(
            conn,
            """
            SELECT speaker, content, created_at
            FROM interview_messages
            WHERE token = ?
            ORDER BY id ASC
            """,
            (token,),
        )
    finally:
        _close(conn)


def delete_interview(token):
    conn = _connect()
    try:
        _execute(conn, "DELETE FROM interview_messages WHERE token = ?", (token,))
        _execute(conn, "DELETE FROM compatibility_checks WHERE token = ?", (token,))
        _execute(conn, "DELETE FROM proctoring_events WHERE token = ?", (token,))
        _execute(conn, "DELETE FROM interviews WHERE token = ?", (token,))
        _commit(conn)
    finally:
        _close(conn)


def save_compatibility_check(token, check_name, status, details=""):
    conn = _connect()
    try:
        _execute(
            conn,
            """
            INSERT INTO compatibility_checks (token, check_name, status, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token, check_name, status, details, _timestamp()),
        )
        _commit(conn)
    finally:
        _close(conn)


def get_compatibility_checks(token):
    conn = _connect()
    try:
        return _execute_fetchall(
            conn,
            """
            SELECT check_name, status, details, created_at
            FROM compatibility_checks
            WHERE token = ?
            ORDER BY id ASC
            """,
            (token,),
        )
    finally:
        _close(conn)


def save_proctoring_event(token, event_type, details=""):
    conn = _connect()
    try:
        _execute(
            conn,
            """
            INSERT INTO proctoring_events (token, event_type, details, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, event_type, details, _timestamp()),
        )
        _commit(conn)
    finally:
        _close(conn)


def get_proctoring_events(token):
    conn = _connect()
    try:
        return _execute_fetchall(
            conn,
            """
            SELECT event_type, details, created_at
            FROM proctoring_events
            WHERE token = ?
            ORDER BY id ASC
            """,
            (token,),
        )
    finally:
        _close(conn)


if __name__ == "__main__":
    init_db()
