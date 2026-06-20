import aiosqlite
import json
from datetime import datetime, date
from config import DEFAULT_SETTINGS, BOUQUET_ACTIVE

DB_PATH = "ren_bot.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            telegram_id INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'florist',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            shift_date TEXT NOT NULL,
            started_at TEXT,
            UNIQUE(user_id, shift_date),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            task_type TEXT NOT NULL,
            task_date TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            photo_file_id TEXT,
            reason TEXT,
            rating INTEGER,
            rated_at TEXT,
            sent_at TEXT,
            completed_at TEXT,
            message_id INTEGER,
            director_message_id INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS bouquets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            photo_file_id TEXT NOT NULL,
            price INTEGER NOT NULL,
            status TEXT DEFAULT 'active',
            rating INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            sold_at TEXT,
            sale_channel TEXT,
            disassembled_at TEXT,
            checked_at TEXT,
            message_id INTEGER,
            director_message_id INTEGER,
            reminder_4_sent INTEGER DEFAULT 0,
            reminder_6_sent INTEGER DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS flowwow_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            next_date TEXT NOT NULL
        );
        """)
        await db.commit()

        for key, value in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value))
            )
        await db.commit()

async def get_setting(key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            if row:
                val = row[0]
                try:
                    return int(val)
                except ValueError:
                    return val
    return DEFAULT_SETTINGS.get(key)

async def set_setting(key: str, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value))
        )
        await db.commit()

async def get_user(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id=?", (telegram_id,)
        ) as cur:
            return await cur.fetchone()

async def get_user_by_id(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id=?", (user_id,)) as cur:
            return await cur.fetchone()

async def create_user(telegram_id: int, name: str, role: str = "florist"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (telegram_id, name, role) VALUES (?, ?, ?)",
            (telegram_id, name, role)
        )
        await db.commit()

async def get_all_florists():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE role='florist' AND is_active=1"
        ) as cur:
            return await cur.fetchall()

async def get_florists_on_shift(shift_date: str = None):
    if not shift_date:
        shift_date = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT u.* FROM users u
            JOIN shifts s ON s.user_id = u.id
            WHERE s.shift_date = ? AND u.is_active = 1
        """, (shift_date,)) as cur:
            return await cur.fetchall()

async def start_shift(user_id: int, shift_date: str = None):
    if not shift_date:
        shift_date = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO shifts (user_id, shift_date, started_at)
            VALUES (?, ?, datetime('now'))
        """, (user_id, shift_date))
        await db.commit()

async def has_shift_today(user_id: int):
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id FROM shifts WHERE user_id=? AND shift_date=?",
            (user_id, today)
        ) as cur:
            return await cur.fetchone() is not None

async def create_task(user_id: int, task_type: str, task_date: str = None, message_id: int = None):
    if not task_date:
        task_date = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO tasks (user_id, task_type, task_date, status, sent_at, message_id)
            VALUES (?, ?, ?, 'pending', datetime('now'), ?)
        """, (user_id, task_type, task_date, message_id))
        await db.commit()
        return cursor.lastrowid

async def get_task(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)) as cur:
            return await cur.fetchone()

async def update_task(task_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [task_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE tasks SET {fields} WHERE id=?", values)
        await db.commit()

async def get_pending_tasks_older_than(minutes: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT t.*, u.telegram_id as florist_tg_id, u.name as florist_name
            FROM tasks t JOIN users u ON u.id = t.user_id
            WHERE t.status = 'pending'
            AND datetime(t.sent_at, '+' || ? || ' minutes') <= datetime('now')
        """, (minutes,)) as cur:
            return await cur.fetchall()

async def get_tasks_for_month(user_id: int, month: str, task_type: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        query = "SELECT * FROM tasks WHERE user_id=? AND task_date LIKE ?"
        params = [user_id, f"{month}%"]
        if task_type:
            query += " AND task_type=?"
            params.append(task_type)
        async with db.execute(query, params) as cur:
            return await cur.fetchall()

async def get_all_tasks_for_month(month: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT t.*, u.name as florist_name, u.telegram_id as florist_tg_id
            FROM tasks t JOIN users u ON u.id = t.user_id
            WHERE t.task_date LIKE ?
        """, (f"{month}%",)) as cur:
            return await cur.fetchall()

# Bouquets
async def create_bouquet(user_id: int, photo_file_id: str, price: int, message_id: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO bouquets (user_id, photo_file_id, price, message_id)
            VALUES (?, ?, ?, ?)
        """, (user_id, photo_file_id, price, message_id))
        await db.commit()
        return cursor.lastrowid

async def get_bouquet(bouquet_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM bouquets WHERE id=?", (bouquet_id,)) as cur:
            return await cur.fetchone()

async def update_bouquet(bouquet_id: int, **kwargs):
    if not kwargs:
        return
    fields = ", ".join(f"{k}=?" for k in kwargs)
    values = list(kwargs.values()) + [bouquet_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE bouquets SET {fields} WHERE id=?", values)
        await db.commit()

async def get_active_bouquets(user_id: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if user_id:
            async with db.execute("""
                SELECT b.*, u.name as florist_name FROM bouquets b
                JOIN users u ON u.id = b.user_id
                WHERE b.status IN ('active', 'checked') AND b.user_id=?
                ORDER BY b.created_at
            """, (user_id,)) as cur:
                return await cur.fetchall()
        else:
            async with db.execute("""
                SELECT b.*, u.name as florist_name FROM bouquets b
                JOIN users u ON u.id = b.user_id
                WHERE b.status IN ('active', 'checked')
                ORDER BY b.created_at
            """) as cur:
                return await cur.fetchall()

async def get_bouquets_needing_check():
    check_days = await get_setting("bouquet_check_days")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT b.*, u.telegram_id as florist_tg_id, u.name as florist_name
            FROM bouquets b JOIN users u ON u.id = b.user_id
            WHERE b.status = 'active'
            AND b.reminder_4_sent = 0
            AND julianday('now') - julianday(b.created_at) >= ?
        """, (check_days,)) as cur:
            return await cur.fetchall()

async def get_bouquets_overdue():
    disassemble_days = await get_setting("bouquet_disassemble_days")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT b.*, u.telegram_id as florist_tg_id, u.name as florist_name
            FROM bouquets b JOIN users u ON u.id = b.user_id
            WHERE b.status IN ('active', 'checked')
            AND b.reminder_6_sent = 0
            AND julianday('now') - julianday(b.created_at) >= ?
        """, (disassemble_days,)) as cur:
            return await cur.fetchall()

async def get_bouquet_stats_for_month(user_id: int, month: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status IN ('sold_studio','sold_flowwow') THEN 1 ELSE 0 END) as sold_total,
                SUM(CASE WHEN status = 'sold_studio' THEN 1 ELSE 0 END) as sold_studio,
                SUM(CASE WHEN status = 'sold_flowwow' THEN 1 ELSE 0 END) as sold_flowwow,
                SUM(CASE WHEN status IN ('sold_studio','sold_flowwow') THEN price ELSE 0 END) as revenue,
                SUM(CASE WHEN status = 'sold_studio' THEN price ELSE 0 END) as revenue_studio,
                SUM(CASE WHEN status = 'sold_flowwow' THEN price ELSE 0 END) as revenue_flowwow,
                SUM(CASE WHEN status = 'disassembled' THEN 1 ELSE 0 END) as disassembled,
                SUM(CASE WHEN status = 'disassembled' THEN price ELSE 0 END) as losses,
                SUM(CASE WHEN status IN ('active','checked') THEN 1 ELSE 0 END) as in_vitrina,
                AVG(CASE WHEN rating IS NOT NULL THEN rating ELSE NULL END) as avg_rating
            FROM bouquets
            WHERE user_id=? AND strftime('%Y-%m', created_at) = ?
        """, (user_id, month)) as cur:
            return await cur.fetchone()

async def count_bouquets_this_month(user_id: int):
    month = date.today().strftime("%Y-%m")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COUNT(*) FROM bouquets
            WHERE user_id=? AND strftime('%Y-%m', created_at) = ?
        """, (user_id, month)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0
