import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_conn():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn


def init_db():
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'florist',
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS shifts (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        date TEXT NOT NULL,
        started_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, date)
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id SERIAL PRIMARY KEY,
        type TEXT NOT NULL,
        assigned_to INTEGER REFERENCES users(id),
        date TEXT NOT NULL,
        scheduled_time TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        photo_file_id TEXT,
        submitted_at TEXT,
        in_hour_at TEXT,
        no_reason TEXT,
        rating INTEGER,
        rated_at TEXT,
        florist_msg_id BIGINT,
        director_msg_id BIGINT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS bouquets (
        id SERIAL PRIMARY KEY,
        florist_id INTEGER NOT NULL REFERENCES users(id),
        photo_file_id TEXT,
        price INTEGER NOT NULL,
        status TEXT DEFAULT 'in_vitrina',
        director_rating INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        checked_at TEXT,
        sold_at TEXT,
        sale_channel TEXT,
        disassembled_at TEXT,
        sent_4day INTEGER DEFAULT 0,
        sent_6day INTEGER DEFAULT 0
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""")

    defaults = {
        "vitrina_bouquets_time":    "14:00",
        "vitrina_compositions_time":"18:00",
        "flowwow_time":             "15:00",
        "shift_start_time":         "10:00",
        "timeout_minutes":          "30",
        "bouquet_check_days":       "4",
        "bouquet_max_days":         "6",
        "flowwow_start_date":       datetime.now().strftime("%Y-%m-%d"),
        "kpi_vitrina_max_skips":    "4",
        "kpi_vitrina_max_norm":     "7",
        "kpi_flowwow_max_skips":    "1",
        "kpi_flowwow_max_norm":     "4",
        "kpi_bouquet_max_bad":      "2",
    }
    for k, v in defaults.items():
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
            (k, v)
        )

    conn.commit()
    cur.close()
    conn.close()


def get_setting(key, default=None):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key=%s", (key,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO settings (key,value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=%s",
        (key, str(value), str(value))
    )
    conn.commit(); cur.close(); conn.close()


def get_all_settings():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings")
    rows = cur.fetchall()
    cur.close(); conn.close()
    return {r["key"]: r["value"] for r in rows}


# ── Users ────────────────────────────────────────────────

def get_user(telegram_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id=%s", (telegram_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def create_user(telegram_id, name, role="florist"):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (telegram_id, name, role) VALUES (%s,%s,%s) ON CONFLICT (telegram_id) DO NOTHING",
        (telegram_id, name, role)
    )
    conn.commit(); cur.close(); conn.close()


def get_director():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE role='director' LIMIT 1")
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_florists(active_only=True):
    conn = get_conn(); cur = conn.cursor()
    q = "SELECT * FROM users WHERE role='florist'"
    if active_only: q += " AND active=1"
    cur.execute(q)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


# ── Shifts ───────────────────────────────────────────────

def start_shift(user_id, date):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO shifts (user_id, date) VALUES (%s,%s) ON CONFLICT (user_id,date) DO NOTHING",
            (user_id, date)
        )
        changed = cur.rowcount > 0
        conn.commit()
    except Exception:
        changed = False
    cur.close(); conn.close()
    return changed


def has_shift(user_id, date):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id FROM shifts WHERE user_id=%s AND date=%s", (user_id, date))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row is not None


def get_working_florists(date):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        """SELECT u.* FROM users u
           JOIN shifts s ON u.id=s.user_id
           WHERE s.date=%s AND u.role='florist' AND u.active=1""",
        (date,)
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_month_shifts(user_id, year_month):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT * FROM shifts WHERE user_id=%s AND date LIKE %s",
        (user_id, f"{year_month}%")
    )
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


# ── Tasks ────────────────────────────────────────────────

def create_task(task_type, assigned_to, date, scheduled_time):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO tasks (type, assigned_to, date, scheduled_time) VALUES (%s,%s,%s,%s) RETURNING id",
        (task_type, assigned_to, date, scheduled_time)
    )
    tid = cur.fetchone()["id"]
    conn.commit(); cur.close(); conn.close()
    return tid


def get_task(task_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE id=%s", (task_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def update_task(task_id, **kwargs):
    conn = get_conn(); cur = conn.cursor()
    sets = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [task_id]
    cur.execute(f"UPDATE tasks SET {sets} WHERE id=%s", vals)
    conn.commit(); cur.close(); conn.close()


def get_pending_task(user_id, task_type, date):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT * FROM tasks WHERE assigned_to=%s AND type=%s AND date=%s AND status IN ('pending','in_hour')",
        (user_id, task_type, date)
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def get_month_tasks(year_month, florist_id=None):
    conn = get_conn(); cur = conn.cursor()
    q = """SELECT t.*, u.name as florist_name FROM tasks t
           JOIN users u ON t.assigned_to=u.id
           WHERE t.date LIKE %s AND u.role='florist'"""
    params = [f"{year_month}%"]
    if florist_id:
        q += " AND t.assigned_to=%s"
        params.append(florist_id)
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_unrated_tasks(hours=24):
    """Задачи поданные флористом но не оценённые директором более N часов."""
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
        SELECT t.*, u.telegram_id as florist_tg, u.name as florist_name
        FROM tasks t JOIN users u ON t.assigned_to=u.id
        WHERE t.status='submitted'
        AND t.submitted_at IS NOT NULL
        AND t.submitted_at < (NOW() - INTERVAL '24 hours')::text
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


# ── Bouquets ─────────────────────────────────────────────

def create_bouquet(florist_id, photo_file_id, price):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "INSERT INTO bouquets (florist_id, photo_file_id, price) VALUES (%s,%s,%s) RETURNING id",
        (florist_id, photo_file_id, price)
    )
    bid = cur.fetchone()["id"]
    conn.commit(); cur.close(); conn.close()
    return bid


def get_bouquet(bouquet_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        "SELECT b.*, u.name as florist_name FROM bouquets b JOIN users u ON b.florist_id=u.id WHERE b.id=%s",
        (bouquet_id,)
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    return dict(row) if row else None


def update_bouquet(bouquet_id, **kwargs):
    conn = get_conn(); cur = conn.cursor()
    sets = ", ".join(f"{k}=%s" for k in kwargs)
    vals = list(kwargs.values()) + [bouquet_id]
    cur.execute(f"UPDATE bouquets SET {sets} WHERE id=%s", vals)
    conn.commit(); cur.close(); conn.close()


def get_active_bouquets(florist_id=None):
    conn = get_conn(); cur = conn.cursor()
    q = """SELECT b.*, u.name as florist_name FROM bouquets b
           JOIN users u ON b.florist_id=u.id
           WHERE b.status='in_vitrina'"""
    params = []
    if florist_id:
        q += " AND b.florist_id=%s"
        params.append(florist_id)
    q += " ORDER BY b.created_at"
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_bouquets_for_check(days, field):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(f"""
        SELECT b.*, u.name as florist_name, u.telegram_id as florist_tg
        FROM bouquets b JOIN users u ON b.florist_id=u.id
        WHERE b.status='in_vitrina'
        AND b.created_at::date = CURRENT_DATE - {days}
        AND b.{field}=0
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]


def get_month_bouquets(year_month, florist_id=None):
    conn = get_conn(); cur = conn.cursor()
    q = """SELECT b.*, u.name as florist_name FROM bouquets b
           JOIN users u ON b.florist_id=u.id
           WHERE b.created_at LIKE %s"""
    params = [f"{year_month}%"]
    if florist_id:
        q += " AND b.florist_id=%s"
        params.append(florist_id)
    cur.execute(q, params)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [dict(r) for r in rows]
