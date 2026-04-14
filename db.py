import sqlite3

conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

def init_db():
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id TEXT PRIMARY KEY,
        name TEXT,
        gender TEXT,
        age INTEGER,
        free_18 INTEGER DEFAULT 4,
        premium_until TEXT,
        referrals INTEGER DEFAULT 0
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        invited_id TEXT
    )
    """)
    conn.commit()

def get_user(uid):
    cur.execute("SELECT * FROM users WHERE telegram_id=?", (uid,))
    return cur.fetchone()

def create_user(uid, name):
    cur.execute("INSERT OR IGNORE INTO users (telegram_id,name) VALUES (?,?)", (uid,name))
    conn.commit()

def update(uid, field, value):
    cur.execute(f"UPDATE users SET {field}=? WHERE telegram_id=?", (value, uid))
    conn.commit()
