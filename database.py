import os
import psycopg2
import psycopg2.extras
from datetime import datetime, date
import pytz

IST = pytz.timezone('Asia/Kolkata')

# Railway injects DATABASE_URL automatically when you add PostgreSQL plugin
DATABASE_URL = os.getenv("DATABASE_URL")


def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id           BIGINT PRIMARY KEY,
            username          TEXT,
            first_name        TEXT,
            total_points      INTEGER DEFAULT 0,
            weekly_points     INTEGER DEFAULT 0,
            total_predictions INTEGER DEFAULT 0,
            joined_at         TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS challenges (
            id            SERIAL PRIMARY KEY,
            date          TEXT UNIQUE,
            symbol        TEXT,
            closing_price REAL DEFAULT NULL,
            is_locked     INTEGER DEFAULT 0,
            is_settled    INTEGER DEFAULT 0,
            created_at    TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id              SERIAL PRIMARY KEY,
            user_id         BIGINT,
            challenge_date  TEXT,
            predicted_price REAL,
            points_earned   INTEGER DEFAULT NULL,
            submitted_at    TEXT,
            UNIQUE(user_id, challenge_date)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS weekly_rewards (
            id            SERIAL PRIMARY KEY,
            week_start    TEXT,
            week_end      TEXT,
            rank          INTEGER,
            user_id       BIGINT,
            username      TEXT,
            points        INTEGER,
            stars_awarded INTEGER,
            awarded_at    TEXT
        )
    """)

    conn.commit()
    c.close()
    conn.close()
    print("✅ PostgreSQL database initialized!")


# ─── USERS ───────────────────────────────────────────

def add_user(user_id: int, username: str, first_name: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (user_id, username, first_name, joined_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO NOTHING
    """, (user_id, username or "", first_name or "", datetime.now(IST).isoformat()))
    conn.commit()
    c.close()
    conn.close()


def get_user(user_id: int):
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    return dict(row) if row else None


def get_all_user_ids():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    c.close()
    conn.close()
    return [r[0] for r in rows]


def add_points(user_id: int, points: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE users
        SET total_points      = total_points + %s,
            weekly_points     = weekly_points + %s,
            total_predictions = total_predictions + 1
        WHERE user_id = %s
    """, (points, points, user_id))
    conn.commit()
    c.close()
    conn.close()


def reset_weekly_points():
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET weekly_points = 0")
    conn.commit()
    c.close()
    conn.close()


# ─── CHALLENGES ──────────────────────────────────────

def set_today_challenge_fixed(symbol: str) -> bool:
    today = str(date.today())
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO challenges (date, symbol, is_locked, is_settled, closing_price, created_at)
            VALUES (%s, %s, 0, 0, NULL, %s)
            ON CONFLICT (date) DO UPDATE
                SET symbol        = EXCLUDED.symbol,
                    is_locked     = 0,
                    is_settled    = 0,
                    closing_price = NULL
        """, (today, symbol.upper(), datetime.now(IST).isoformat()))
        conn.commit()
        c.close()
        conn.close()
        return True
    except Exception as e:
        conn.rollback()
        c.close()
        conn.close()
        print(f"set_today_challenge error: {e}")
        return False


def get_today_challenge():
    today = str(date.today())
    conn = get_conn()
    c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("SELECT * FROM challenges WHERE date = %s", (today,))
    row = c.fetchone()
    c.close()
    conn.close()
    return dict(row) if row else None


def lock_today_challenge():
    today = str(date.today())
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE challenges SET is_locked = 1 WHERE date = %s", (today,))
    conn.commit()
    c.close()
    conn.close()


def settle_challenge(closing_price: float) -> bool:
    today = str(date.today())
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE challenges
        SET closing_price = %s, is_settled = 1, is_locked = 1
        WHERE date = %s
    """, (closing_price, today))
    conn.commit()
    c.close()
    conn.close()
    return True


# ─── PREDICTIONS ─────────────────────────────────────

def submit_prediction(user_id: int, predicted_price: float) -> tuple:
    today     = str(date.today())
    challenge = get_today_challenge()

    if not challenge:
        return False, "no_challenge"
    if challenge["is_locked"]:
        return False, "locked"
    if challenge["is_settled"]:
        return False, "settled"

    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("""
            INSERT INTO predictions (user_id, challenge_date, predicted_price, submitted_at)
            VALUES (%s, %s, %s, %s)
        """, (user_id, today, predicted_price, datetime.now(IST).isoformat()))
        conn.commit()
        c.close()
        conn.close()
        return True, "ok"
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        c.close()
        conn.close()
        return False, "duplicate"
    except Exception as e:
        conn.rollback()
        c.close()
        conn.close()
        print(f"submit_prediction error: {e}")
        return False, "error"


def update_prediction(user_id: int, predicted_price: float) -> bool:
    today = str(date.today())
    conn  = get_conn()
    c     = conn.cursor()
    c.execute("""
        UPDATE predictions
        SET predicted_price = %s, submitted_at = %s
        WHERE user_id = %s AND challenge_date = %s
    """, (predicted_price, datetime.now(IST).isoformat(), user_id, today))
    conn.commit()
    c.close()
    conn.close()
    return True


def get_today_prediction(user_id: int):
    today = str(date.today())
    conn  = get_conn()
    c     = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""
        SELECT * FROM predictions
        WHERE user_id = %s AND challenge_date = %s
    """, (user_id, today))
    row = c.fetchone()
    c.close()
    conn.close()
    return dict(row) if row else None


def get_all_today_predictions():
    today = str(date.today())
    conn  = get_conn()
    c     = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""
        SELECT p.*, u.username, u.first_name
        FROM predictions p
        JOIN users u ON p.user_id = u.user_id
        WHERE p.challenge_date = %s AND p.points_earned IS NULL
    """, (today,))
    rows = c.fetchall()
    c.close()
    conn.close()
    return [dict(r) for r in rows]


def save_prediction_points(prediction_id: int, points: int):
    conn = get_conn()
    c    = conn.cursor()
    c.execute("UPDATE predictions SET points_earned = %s WHERE id = %s", (points, prediction_id))
    conn.commit()
    c.close()
    conn.close()


def get_user_prediction_history(user_id: int, limit: int = 7):
    conn = get_conn()
    c    = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""
        SELECT p.challenge_date, p.predicted_price, p.points_earned,
               ch.symbol, ch.closing_price
        FROM predictions p
        LEFT JOIN challenges ch ON p.challenge_date = ch.date
        WHERE p.user_id = %s
        ORDER BY p.challenge_date DESC
        LIMIT %s
    """, (user_id, limit))
    rows = c.fetchall()
    c.close()
    conn.close()
    return [dict(r) for r in rows]


# ─── LEADERBOARD ─────────────────────────────────────

def get_all_time_leaderboard(limit: int = 10):
    conn = get_conn()
    c    = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""
        SELECT user_id, username, first_name, total_points, total_predictions
        FROM users
        WHERE total_points > 0
        ORDER BY total_points DESC
        LIMIT %s
    """, (limit,))
    rows = c.fetchall()
    c.close()
    conn.close()
    return [dict(r) for r in rows]


def get_weekly_leaderboard(limit: int = 10):
    conn = get_conn()
    c    = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    c.execute("""
        SELECT user_id, username, first_name, weekly_points, total_predictions
        FROM users
        WHERE weekly_points > 0
        ORDER BY weekly_points DESC
        LIMIT %s
    """, (limit,))
    rows = c.fetchall()
    c.close()
    conn.close()
    return [dict(r) for r in rows]


def get_user_rank(user_id: int) -> dict:
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        SELECT COUNT(*) + 1 FROM users
        WHERE total_points > (
            SELECT COALESCE(total_points, 0) FROM users WHERE user_id = %s
        )
    """, (user_id,))
    at_rank = c.fetchone()[0]

    c.execute("""
        SELECT COUNT(*) + 1 FROM users
        WHERE weekly_points > (
            SELECT COALESCE(weekly_points, 0) FROM users WHERE user_id = %s
        )
    """, (user_id,))
    wk_rank = c.fetchone()[0]

    c.close()
    conn.close()
    return {"all_time": at_rank, "weekly": wk_rank}


# ─── WEEKLY REWARDS ──────────────────────────────────

def log_weekly_reward(week_start, week_end, rank, user_id, username, points, stars):
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        INSERT INTO weekly_rewards
            (week_start, week_end, rank, user_id, username, points, stars_awarded, awarded_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (week_start, week_end, rank, user_id, username, points, stars,
          datetime.now(IST).isoformat()))
    conn.commit()
    c.close()
    conn.close()