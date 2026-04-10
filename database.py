import sqlite3
import uuid
from datetime import datetime

DB_NAME = "interviews.db"


def _connect():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn, table_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _ensure_column(conn, table_name, column_name, column_type):
    if column_name not in _table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def init_db():
    conn = _connect()
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
            transcript TEXT
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

    # Migrate older databases in place.
    _ensure_column(conn, "interviews", "status", "TEXT DEFAULT 'scheduled'")
    _ensure_column(conn, "interviews", "started_at", "TEXT")
    _ensure_column(conn, "interviews", "completed_at", "TEXT")
    _ensure_column(conn, "interviews", "duration_minutes", "REAL")
    _ensure_column(conn, "interviews", "score", "INTEGER")
    _ensure_column(conn, "interviews", "feedback", "TEXT")
    _ensure_column(conn, "interviews", "transcript", "TEXT")

    conn.commit()
    conn.close()


def create_admin(username, password_hash):
    conn = _connect()
    cursor = conn.execute(
        """
        INSERT INTO admins (username, password_hash, created_at)
        VALUES (?, ?, ?)
        """,
        (username, password_hash, datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    admin_id = cursor.lastrowid
    conn.close()
    return admin_id


def get_admin_by_username(username):
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM admins WHERE username = ?",
        (username,),
    ).fetchone()
    conn.close()
    return row


def get_admin_by_id(admin_id):
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM admins WHERE id = ?",
        (admin_id,),
    ).fetchone()
    conn.close()
    return row


def schedule_interview(name, email, interview_time):
    token = str(uuid.uuid4())
    conn = _connect()
    conn.execute(
        """
        INSERT INTO interviews (
            candidate_name, candidate_email, interview_time, token, status
        ) VALUES (?, ?, ?, ?, 'scheduled')
        """,
        (name, email, interview_time, token),
    )
    conn.commit()
    conn.close()
    return token


def get_interview_by_token(token):
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM interviews WHERE token = ?",
        (token,),
    ).fetchone()
    conn.close()
    return row


def get_all_interviews():
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM interviews ORDER BY interview_time DESC, id DESC"
    ).fetchall()
    conn.close()
    return rows


def update_interview_started(token):
    conn = _connect()
    conn.execute(
        """
        UPDATE interviews
        SET status = 'in_progress',
            started_at = COALESCE(started_at, ?)
        WHERE token = ? AND status != 'completed'
        """,
        (datetime.utcnow().isoformat(timespec="seconds"), token),
    )
    conn.commit()
    conn.close()


def complete_interview(token, score, feedback, transcript, duration_minutes):
    conn = _connect()
    conn.execute(
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
            datetime.utcnow().isoformat(timespec="seconds"),
            duration_minutes,
            score,
            feedback,
            transcript,
            token,
        ),
    )
    conn.commit()
    conn.close()


def save_interview_message(token, speaker, content):
    conn = _connect()
    conn.execute(
        """
        INSERT INTO interview_messages (token, speaker, content, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (token, speaker, content, datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def get_interview_messages(token):
    conn = _connect()
    rows = conn.execute(
        """
        SELECT speaker, content, created_at
        FROM interview_messages
        WHERE token = ?
        ORDER BY id ASC
        """,
        (token,),
    ).fetchall()
    conn.close()
    return rows


def delete_interview(token):
    conn = _connect()
    conn.execute("DELETE FROM interview_messages WHERE token = ?", (token,))
    conn.execute("DELETE FROM compatibility_checks WHERE token = ?", (token,))
    conn.execute("DELETE FROM proctoring_events WHERE token = ?", (token,))
    conn.execute("DELETE FROM interviews WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def save_compatibility_check(token, check_name, status, details=""):
    conn = _connect()
    conn.execute(
        """
        INSERT INTO compatibility_checks (token, check_name, status, details, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (token, check_name, status, details, datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def get_compatibility_checks(token):
    conn = _connect()
    rows = conn.execute(
        """
        SELECT check_name, status, details, created_at
        FROM compatibility_checks
        WHERE token = ?
        ORDER BY id ASC
        """,
        (token,),
    ).fetchall()
    conn.close()
    return rows


def save_proctoring_event(token, event_type, details=""):
    conn = _connect()
    conn.execute(
        """
        INSERT INTO proctoring_events (token, event_type, details, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (token, event_type, details, datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def get_proctoring_events(token):
    conn = _connect()
    rows = conn.execute(
        """
        SELECT event_type, details, created_at
        FROM proctoring_events
        WHERE token = ?
        ORDER BY id ASC
        """,
        (token,),
    ).fetchall()
    conn.close()
    return rows


if __name__ == "__main__":
    init_db()
