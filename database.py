import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date
import pytz

DATABASE_URL = os.getenv("DATABASE_URL")
IST = pytz.timezone("Asia/Kolkata")

def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        is_premium BOOLEAN DEFAULT FALSE,
        is_banned BOOLEAN DEFAULT FALSE,
        total_points REAL DEFAULT 0,
        weekly_points REAL DEFAULT 0,
        predictions_made INTEGER DEFAULT 0,
        joined_at TIMESTAMP DEFAULT NOW(),
        last_active TIMESTAMP DEFAULT NOW()
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS predictions (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        stock_symbol TEXT,
        predicted_price REAL,
        actual_price REAL,
        points_earned REAL DEFAULT 0,
        prediction_date DATE,
        is_evaluated BOOLEAN DEFAULT FALSE,
        submitted_at TIMESTAMP DEFAULT NOW()
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS daily_stocks (
        id SERIAL PRIMARY KEY,
        stock_date DATE UNIQUE,
        nifty_closing REAL,
        banknifty_closing REAL,
        sensex_closing REAL,
        results_announced BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW()
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS weekly_winners (
        id SERIAL PRIMARY KEY,
        week_start DATE,
        week_end DATE,
        rank1_user_id BIGINT,
        rank2_user_id BIGINT,
        rank3_user_id BIGINT,
        rank1_points REAL,
        rank2_points REAL,
        rank3_points REAL,
        stars_sent BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT NOW()
    )''')

    conn.commit()
    conn.close()
    print("StockTap database ready!")

def add_user(user_id, username, first_name=None, last_name=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO users (user_id, username, first_name, last_name)
                 VALUES (%s, %s, %s, %s)
                 ON CONFLICT (user_id) DO UPDATE SET
                 last_active = NOW(),
                 username = EXCLUDED.username,
                 first_name = EXCLUDED.first_name''',
              (user_id, username, first_name, last_name))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def is_premium(user_id):
    user = get_user(user_id)
    return user and user["is_premium"]

def is_banned(user_id):
    user = get_user(user_id)
    return user and user["is_banned"]

def set_premium(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET is_premium = TRUE WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()

def remove_premium(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET is_premium = FALSE WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()

def ban_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = TRUE WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET is_banned = FALSE WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()

def get_predictions_today(user_id, prediction_date):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT COUNT(*) FROM predictions
                 WHERE user_id = %s AND prediction_date = %s""",
              (user_id, prediction_date))
    count = c.fetchone()[0]
    conn.close()
    return count

def has_predicted_stock_today(user_id, stock_symbol, prediction_date):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT COUNT(*) FROM predictions
                 WHERE user_id = %s AND stock_symbol = %s
                 AND prediction_date = %s""",
              (user_id, stock_symbol, prediction_date))
    count = c.fetchone()[0]
    conn.close()
    return count > 0

def add_prediction(user_id, stock_symbol, predicted_price, prediction_date):
    conn = get_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO predictions
                 (user_id, stock_symbol, predicted_price, prediction_date)
                 VALUES (%s, %s, %s, %s)''',
              (user_id, stock_symbol, predicted_price, prediction_date))
    conn.commit()
    conn.close()

def get_user_predictions_today(user_id, prediction_date):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("""SELECT * FROM predictions
                 WHERE user_id = %s AND prediction_date = %s
                 ORDER BY submitted_at DESC""",
              (user_id, prediction_date))
    predictions = c.fetchall()
    conn.close()
    return predictions

def get_all_predictions_for_date(prediction_date):
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("""SELECT * FROM predictions
                 WHERE prediction_date = %s AND is_evaluated = FALSE""",
              (prediction_date,))
    predictions = c.fetchall()
    conn.close()
    return predictions

def evaluate_prediction(prediction_id, actual_price, points):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""UPDATE predictions SET
                 actual_price = %s,
                 points_earned = %s,
                 is_evaluated = TRUE
                 WHERE id = %s""",
              (actual_price, points, prediction_id))
    conn.commit()
    conn.close()

def update_user_points(user_id, points):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""UPDATE users SET
                 total_points = total_points + %s,
                 weekly_points = weekly_points + %s,
                 predictions_made = predictions_made + 1
                 WHERE user_id = %s""",
              (points, points, user_id))
    conn.commit()
    conn.close()

def get_weekly_leaderboard():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("""SELECT user_id, username, first_name,
                 weekly_points, is_premium
                 FROM users
                 WHERE weekly_points > 0
                 ORDER BY weekly_points DESC
                 LIMIT 10""")
    leaders = c.fetchall()
    conn.close()
    return leaders

def get_user_weekly_rank(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""SELECT COUNT(*) + 1 FROM users
                 WHERE weekly_points > (
                     SELECT weekly_points FROM users WHERE user_id = %s
                 )""", (user_id,))
    rank = c.fetchone()[0]
    conn.close()
    return rank

def reset_weekly_points():
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE users SET weekly_points = 0")
    conn.commit()
    conn.close()

def save_weekly_winners(week_start, week_end, leaders):
    conn = get_conn()
    c = conn.cursor()
    r1 = leaders[0] if len(leaders) > 0 else None
    r2 = leaders[1] if len(leaders) > 1 else None
    r3 = leaders[2] if len(leaders) > 2 else None
    c.execute('''INSERT INTO weekly_winners
                 (week_start, week_end,
                  rank1_user_id, rank2_user_id, rank3_user_id,
                  rank1_points, rank2_points, rank3_points)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
              (week_start, week_end,
               r1["user_id"] if r1 else None,
               r2["user_id"] if r2 else None,
               r3["user_id"] if r3 else None,
               r1["weekly_points"] if r1 else 0,
               r2["weekly_points"] if r2 else 0,
               r3["weekly_points"] if r3 else 0))
    conn.commit()
    conn.close()

def get_all_user_ids():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_banned = FALSE")
    ids = [row[0] for row in c.fetchall()]
    conn.close()
    return ids

def get_all_users():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM users ORDER BY joined_at DESC")
    users = c.fetchall()
    conn.close()
    return users

def get_stats():
    conn = get_conn()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT COUNT(*) as total FROM users")
    total = c.fetchone()["total"]
    c.execute("SELECT COUNT(*) as total FROM users WHERE is_premium = TRUE")
    premium = c.fetchone()["total"]
    c.execute("SELECT COUNT(*) as total FROM predictions")
    predictions = c.fetchone()["total"]
    c.execute("SELECT COUNT(*) as total FROM users WHERE joined_at > NOW() - INTERVAL '24 hours'")
    new_today = c.fetchone()["total"]
    conn.close()
    return {
        "total_users": total,
        "premium_users": premium,
        "free_users": total - premium,
        "total_predictions": predictions,
        "new_today": new_today
    }