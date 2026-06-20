import sqlite3
from datetime import datetime
from config import DATABASE_PATH


def get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        name TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'florist',
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS shifts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        started_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(user_id, date)
    );
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        assigned_to INTEGER,
        date TEXT NOT NULL,
        scheduled_time TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        photo_file_id TEXT,
        submitted_at TEXT,
        in_hour_at TEXT,
        no_reason TEXT,
        rating INTEGER,
        rated_at TEXT,
        florist_msg_id INTEGER,
        director_msg_id INTEGER,
        FOREIGN KEY (assigned_to) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS bouquets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        florist_id INTEGER NOT NULL,
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
        sent_6day INTEGER DEFAULT 0,
        FOREIGN KEY (florist_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)
    defaults = {
        "vitrina_bouquets_time": "14:00",
        "vitrina_compositions_time": "18:00",
        "flowwow_time": "15:00",
        "shift_start_time": "10:00",
        "timeout_minutes": "30",
        "bouquet_check_days": "4",
        "bouquet_max_days": "6",
        "flowwow_start_date": datetime.now().strftime("%Y-%m-%d"),
        "kpi_vitrina_max_skips": "4",
        "kpi_vitrina_max_norm": "7",
        "kpi_flowwow_max_skips": "1",
        "kpi_flowwow_max_norm": "4",
        "kpi_bouquet_max_bad": "2",
    }
    for k, v in defaults.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", (k, v))
    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))
    conn.commit()
    conn.close()


def get_all_settings():
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def get_user(telegram_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(telegram_id, name, role="florist"):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO users (telegram_id, name, role) VALUES (?,?,?)", (telegram_id, name, role))
    conn.commit()
    conn.close()


def get_director():
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE role='director' LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


def get_florists(active_only=True):
    conn = get_conn()
    q = "SELECT * FROM users WHERE role='florist'"
    if active_only:
        q += " AND active=1"
    rows = conn.execute(q).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def start_shift(user_id, date):
    conn = get_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO shifts (user_id, date) VALUES (?,?)", (user_id, date))
        conn.commit()
        changed = conn.total_changes > 0
    except Exception:
        changed = False
    conn.close()
    return changed


def has_shift(user_id, date):
    conn = get_conn()
    row = conn.execute("SELECT id FROM shifts WHERE user_id=? AND date=?", (user_id, date)).fetchone()
    conn.close()
    return row is not None


def get_working_florists(date):
    conn = get_conn()
    rows = conn.execute(
        "SELECT u.* FROM users u JOIN shifts s ON u.id=s.user_id WHERE s.date=? AND u.role='florist' AND u.active=1",
        (date,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_month_shifts(user_id, year_month):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM shifts WHERE user_id=? AND date LIKE ?", (user_id, f"{year_month}%")).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_task(task_type, assigned_to, date, scheduled_time):
    conn = get_conn()
    cur = conn.execute("INSERT INTO tasks (type, assigned_to, date, scheduled_time) VALUES (?,?,?,?)",
                       (task_type, assigned_to, date, scheduled_time))
    tid = cur.lastrowid
    conn.commit()
    conn.close()
    return tid


def get_task(task_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_task(task_id, **kwargs):
    conn = get_conn()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [task_id]
    conn.execute(f"UPDATE tasks SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()


def get_pending_task(user_id, task_type, date):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM tasks WHERE assigned_to=? AND type=? AND date=? AND status IN ('pending','in_hour')",
        (user_id, task_type, date)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_month_tasks(year_month, florist_id=None):
    conn = get_conn()
    q = "SELECT t.*, u.name as florist_name FROM tasks t JOIN users u ON t.assigned_to=u.id WHERE t.date LIKE ? AND u.role='florist'"
    params = [f"{year_month}%"]
    if florist_id:
        q += " AND t.assigned_to=?"
        params.append(florist_id)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_bouquet(florist_id, photo_file_id, price):
    conn = get_conn()
    cur = conn.execute("INSERT INTO bouquets (florist_id, photo_file_id, price) VALUES (?,?,?)",
                       (florist_id, photo_file_id, price))
    bid = cur.lastrowid
    conn.commit()
    conn.close()
    return bid


def get_bouquet(bouquet_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT b.*, u.name as florist_name FROM bouquets b JOIN users u ON b.florist_id=u.id WHERE b.id=?",
        (bouquet_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_bouquet(bouquet_id, **kwargs):
    conn = get_conn()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [bouquet_id]
    conn.execute(f"UPDATE bouquets SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()


def get_active_bouquets(florist_id=None):
    conn = get_conn()
    q = "SELECT b.*, u.name as florist_name FROM bouquets b JOIN users u ON b.florist_id=u.id WHERE b.status='in_vitrina'"
    params = []
    if florist_id:
        q += " AND b.florist_id=?"
        params.append(florist_id)
    q += " ORDER BY b.created_at"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_bouquets_for_check(days, field):
    conn = get_conn()
    rows = conn.execute(
        f"SELECT b.*, u.name as florist_name, u.telegram_id as florist_tg FROM bouquets b JOIN users u ON b.florist_id=u.id WHERE b.status='in_vitrina' AND date(b.created_at)=date('now','-{days} days') AND b.{field}=0"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_month_bouquets(year_month, florist_id=None):
    conn = get_conn()
    q = "SELECT b.*, u.name as florist_name FROM bouquets b JOIN users u ON b.florist_id=u.id WHERE b.created_at LIKE ?"
    params = [f"{year_month}%"]
    if florist_id:
        q += " AND b.florist_id=?"
        params.append(florist_id)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
