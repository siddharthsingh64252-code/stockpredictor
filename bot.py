import logging
import os
import pytz
from datetime import datetime, time, timedelta, date
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

from database import (
    init_db, add_user, get_user, get_all_user_ids,
    add_points, reset_weekly_points, log_weekly_reward,
    set_today_challenge_fixed, get_today_challenge,
    lock_today_challenge, settle_challenge,
    submit_prediction, update_prediction,
    get_today_prediction, get_all_today_predictions,
    save_prediction_points, get_user_prediction_history,
    get_all_time_leaderboard, get_weekly_leaderboard,
    get_user_rank
)
from price_checker import get_stock_price, get_closing_price
from points import calculate_points, points_breakdown_text

# ─── SETUP ───────────────────────────────────────────
load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID  = int(os.getenv("ADMIN_ID", "0"))
IST       = pytz.timezone("Asia/Kolkata")

WEEKLY_PRIZES = {1: 100, 2: 50, 3: 25}

# ─── HELPERS ─────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def medal(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")

def display_name(user: dict) -> str:
    return user.get("first_name") or user.get("username") or "User"

# ─── KEYBOARDS ───────────────────────────────────────

def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎯 Predict Today", callback_data="predict"),
            InlineKeyboardButton("📊 My Stats",      callback_data="stats"),
        ],
        [
            InlineKeyboardButton("🏆 Leaderboard",   callback_data="leaderboard"),
            InlineKeyboardButton("📅 My History",    callback_data="history"),
        ],
        [
            InlineKeyboardButton("❓ How It Works",  callback_data="howto"),
        ],
    ])

def back_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ])

# ─── /start ──────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)

    challenge  = get_today_challenge()
    stock_line = (
        f"📌 Today's stock: *{challenge['symbol']}*"
        + (" _(locked)_" if challenge["is_locked"] else "")
        if challenge else "⏳ Today's stock not announced yet!"
    )

    await update.message.reply_text(
        f"Namaste *{user.first_name}*! 🙏\n\n"
        "Welcome to *StockPredictor* 📈\n"
        "Predict closing prices → earn points → win *⭐ Stars*!\n\n"
        f"{stock_line}\n\n"
        "🎯 Exact match = *1000 pts*\n"
        "📅 Deadline: *9:00 AM IST* daily\n\n"
        "👇 Choose an option:",
        parse_mode="Markdown",
        reply_markup=main_menu()
    )

# ─── CALLBACK ROUTER ─────────────────────────────────

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data    = query.data

    # ── MAIN MENU ──
    if data == "main_menu":
        challenge  = get_today_challenge()
        stock_line = (
            f"📌 Today: *{challenge['symbol']}*"
            + (" _(locked)_" if challenge["is_locked"] else "")
            if challenge else "⏳ No stock announced yet"
        )
        await query.edit_message_text(
            f"🏠 *Main Menu*\n\n{stock_line}\n\nChoose an option 👇",
            parse_mode="Markdown",
            reply_markup=main_menu()
        )

    # ── PREDICT ──
    elif data == "predict":
        await handle_predict_callback(query, context)

    # ── EDIT PREDICTION ──
    elif data == "edit_prediction":
        challenge = get_today_challenge()
        if not challenge or challenge["is_locked"]:
            await query.edit_message_text(
                "⏰ *Predictions are locked!*\nMarket is open — no more changes.",
                parse_mode="Markdown", reply_markup=back_menu()
            )
            return
        context.user_data["editing"] = True
        await query.edit_message_text(
            f"✏️ *Edit Your Prediction*\n\n"
            f"Stock: *{challenge['symbol']}*\n\n"
            "Send your new predicted closing price 👇\n"
            "_(Numbers only, e.g. `24500.50`)_",
            parse_mode="Markdown"
        )

    # ── STATS ──
    elif data == "stats":
        user = get_user(user_id)
        if not user:
            await query.edit_message_text("Please /start first.")
            return
        rank = get_user_rank(user_id)
        pred = get_today_prediction(user_id)
        pred_line = (
            f"🎯 Today's prediction: *₹{pred['predicted_price']}*"
            if pred else "🎯 Today: _Not predicted yet_"
        )
        await query.edit_message_text(
            f"📊 *Your Stats*\n\n"
            f"👤 Name: *{display_name(user)}*\n"
            f"🏅 All-time rank: *#{rank['all_time']}*\n"
            f"📅 Weekly rank: *#{rank['weekly']}*\n\n"
            f"⭐ Total points: *{user['total_points']}*\n"
            f"📆 Weekly points: *{user['weekly_points']}*\n"
            f"🎮 Total predictions: *{user['total_predictions']}*\n\n"
            f"{pred_line}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 My History", callback_data="history")],
                [InlineKeyboardButton("🏠 Main Menu",  callback_data="main_menu")],
            ])
        )

    # ── LEADERBOARD ──
    elif data == "leaderboard":
        await show_leaderboard(query)

    elif data == "leaderboard_weekly":
        await show_weekly_leaderboard(query)

    elif data == "leaderboard_alltime":
        await show_leaderboard(query)

    # ── HISTORY ──
    elif data == "history":
        history = get_user_prediction_history(user_id, limit=7)
        if not history:
            await query.edit_message_text(
                "📅 *No history yet!*\n\nStart predicting to see results here.",
                parse_mode="Markdown", reply_markup=back_menu()
            )
            return

        text = "📅 *Your Last 7 Predictions:*\n\n"
        for h in history:
            pts       = h["points_earned"]
            closing   = h["closing_price"]
            pts_str   = f"*{pts} pts*" if pts is not None else "_pending_"
            close_str = f"₹{closing}"  if closing           else "_pending_"
            text += (
                f"📌 *{h['symbol']}* | {h['challenge_date']}\n"
                f"   Guess: ₹{h['predicted_price']} | Close: {close_str}\n"
                f"   Points: {pts_str}\n\n"
            )

        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=back_menu()
        )

    # ── HOW IT WORKS ──
    elif data == "howto":
        await query.edit_message_text(
            "❓ *How StockPredictor Works*\n\n"
            "1️⃣ Admin announces today's stock daily\n"
            "2️⃣ You predict the *closing price* before *9:00 AM IST*\n"
            "3️⃣ Market closes at *3:30 PM IST*\n"
            "4️⃣ Points awarded based on accuracy\n"
            "5️⃣ Top 3 each week win *⭐ Telegram Stars*!\n\n"
            + points_breakdown_text() + "\n\n"
            "🏆 *Weekly Prizes:*\n"
            "🥇 1st → *100 ⭐ Stars*\n"
            "🥈 2nd → *50 ⭐ Stars*\n"
            "🥉 3rd → *25 ⭐ Stars*\n\n"
            "🔄 Week resets every *Monday 12 AM IST*",
            parse_mode="Markdown", reply_markup=back_menu()
        )

# ─── PREDICT FLOW ─────────────────────────────────────

async def handle_predict_callback(query, context):
    user_id   = query.from_user.id
    challenge = get_today_challenge()

    if not challenge:
        await query.edit_message_text(
            "⏳ *No stock announced today!*\n\nCome back later.",
            parse_mode="Markdown", reply_markup=back_menu()
        )
        return

    if challenge["is_locked"]:
        existing = get_today_prediction(user_id)
        pts_line = ""
        if existing and existing["points_earned"] is not None:
            pts_line = f"\n✅ You earned *{existing['points_earned']} pts* today!"
        elif existing:
            pts_line = "\n⏳ Awaiting market close for results."

        await query.edit_message_text(
            f"🔒 *Predictions Locked!*\n\n"
            f"Stock: *{challenge['symbol']}*\n"
            f"{'Your prediction: ₹' + str(existing['predicted_price']) if existing else '⚠️ You did not predict today.'}"
            f"{pts_line}",
            parse_mode="Markdown", reply_markup=back_menu()
        )
        return

    existing = get_today_prediction(user_id)
    if existing:
        await query.edit_message_text(
            f"✅ *Already Predicted Today!*\n\n"
            f"Stock: *{challenge['symbol']}*\n"
            f"Your prediction: *₹{existing['predicted_price']}*\n\n"
            "You can edit until *9:00 AM IST* 👇",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ Edit Prediction", callback_data="edit_prediction")],
                [InlineKeyboardButton("🏠 Main Menu",       callback_data="main_menu")],
            ])
        )
        return

    live = get_stock_price(challenge["symbol"])
    hint = f"\n💰 Current price: *₹{live}*" if live else ""

    await query.edit_message_text(
        f"🎯 *Predict Closing Price*\n\n"
        f"Stock: *{challenge['symbol']}*{hint}\n\n"
        "Send your predicted *closing price* 👇\n"
        "_(Numbers only, e.g. `24500.50`)_\n\n"
        "⏰ Deadline: *9:00 AM IST*",
        parse_mode="Markdown"
    )
    context.user_data["expecting_prediction"] = True

# ─── TEXT MESSAGE HANDLER ─────────────────────────────

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id
    text    = update.message.text.strip()

    add_user(user_id, user.username, user.first_name)

    if context.user_data.get("expecting_prediction") or context.user_data.get("editing"):
        try:
            price = float(text.replace(",", "").replace("₹", "").strip())
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid number!\nSend like `24500` or `24500.50`",
                parse_mode="Markdown"
            )
            return

        editing = context.user_data.pop("editing", False)
        context.user_data.pop("expecting_prediction", None)

        challenge = get_today_challenge()
        if not challenge:
            await update.message.reply_text("⏳ No challenge today!", reply_markup=main_menu())
            return
        if challenge["is_locked"]:
            await update.message.reply_text(
                "🔒 *Predictions are locked!*",
                parse_mode="Markdown", reply_markup=main_menu()
            )
            return

        if editing:
            update_prediction(user_id, price)
            await update.message.reply_text(
                f"✅ *Prediction Updated!*\n\n"
                f"Stock: *{challenge['symbol']}*\n"
                f"New guess: *₹{price}*\n\nGood luck! 🍀",
                parse_mode="Markdown", reply_markup=main_menu()
            )
            return

        success, reason = submit_prediction(user_id, price)

        if success:
            await update.message.reply_text(
                f"✅ *Prediction Submitted!*\n\n"
                f"Stock: *{challenge['symbol']}*\n"
                f"Your guess: *₹{price}*\n\n"
                "Results after 3:30 PM IST 📊\nGood luck! 🍀",
                parse_mode="Markdown", reply_markup=main_menu()
            )
        elif reason == "duplicate":
            pred = get_today_prediction(user_id)
            await update.message.reply_text(
                f"⚠️ Already predicted *₹{pred['predicted_price']}* today!\n"
                "Use ✏️ Edit to change it.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ Edit Prediction", callback_data="edit_prediction")],
                    [InlineKeyboardButton("🏠 Main Menu",       callback_data="main_menu")],
                ])
            )
        elif reason == "locked":
            await update.message.reply_text("🔒 Predictions locked!", reply_markup=main_menu())
        else:
            await update.message.reply_text("❌ Error. Try again.", reply_markup=main_menu())
        return

    await update.message.reply_text("👇 Use the menu:", reply_markup=main_menu())

# ─── LEADERBOARD DISPLAYS ────────────────────────────

async def show_leaderboard(query):
    weekly = get_weekly_leaderboard(3)
    all_t  = get_all_time_leaderboard(10)

    week_text = "🏆 *This Week's Top 3:*\n"
    for i, r in enumerate(weekly[:3], 1):
        stars = f" ⭐{WEEKLY_PRIZES[i]}" if i in WEEKLY_PRIZES else ""
        week_text += f"{medal(i)} {r['first_name'] or r['username']} — *{r['weekly_points']} pts*{stars}\n"
    if not weekly:
        week_text += "_No predictions this week_\n"

    all_text = "\n📊 *All-Time Top 10:*\n"
    for i, r in enumerate(all_t, 1):
        all_text += f"{medal(i)} {r['first_name'] or r['username']} — *{r['total_points']} pts*\n"
    if not all_t:
        all_text += "_No predictions yet_\n"

    await query.edit_message_text(
        week_text + all_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 Weekly Board",   callback_data="leaderboard_weekly")],
            [InlineKeyboardButton("🏠 Main Menu",      callback_data="main_menu")],
        ])
    )


async def show_weekly_leaderboard(query):
    rows = get_weekly_leaderboard(10)
    text = "📅 *Weekly Leaderboard:*\n\n"
    for i, r in enumerate(rows, 1):
        stars = f" — ⭐{WEEKLY_PRIZES[i]}" if i in WEEKLY_PRIZES else ""
        text += f"{medal(i)} {r['first_name'] or r['username']} — *{r['weekly_points']} pts*{stars}\n"
    if not rows:
        text += "_No predictions this week_"
    text += "\n\n🔄 Resets every *Monday 12 AM IST*"

    await query.edit_message_text(
        text, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 All-Time Board", callback_data="leaderboard_alltime")],
            [InlineKeyboardButton("🏠 Main Menu",      callback_data="main_menu")],
        ])
    )

# ─── ADMIN COMMANDS ───────────────────────────────────

async def cmd_setstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setstock RELIANCE`", parse_mode="Markdown")
        return

    symbol = context.args[0].upper()
    price  = get_stock_price(symbol)
    if price is None:
        await update.message.reply_text(f"❌ Could not fetch *{symbol}*. Check symbol.", parse_mode="Markdown")
        return

    set_today_challenge_fixed(symbol)
    msg = (
        f"📢 *Today's Prediction Challenge!*\n\n"
        f"📌 Stock: *{symbol}*\n"
        f"💰 Current: *₹{price}*\n\n"
        f"🎯 Predict today's *closing price*!\n"
        f"⏰ Deadline: *9:00 AM IST*\n\n"
        "Use /start → 🎯 Predict Today"
    )
    sent, failed = await broadcast(context, msg)
    await update.message.reply_text(
        f"✅ Stock set: *{symbol}* (₹{price})\n📢 Sent: {sent} | Failed: {failed}",
        parse_mode="Markdown"
    )


async def cmd_settle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return

    challenge = get_today_challenge()
    if not challenge:
        await update.message.reply_text("❌ No challenge today.")
        return
    if challenge["is_settled"]:
        await update.message.reply_text("✅ Already settled today.")
        return

    closing = get_closing_price(challenge["symbol"])
    if closing is None:
        await update.message.reply_text(
            f"❌ Could not auto-fetch closing for *{challenge['symbol']}*.\n\n"
            "Use: `/setclosing <price>`",
            parse_mode="Markdown"
        )
        return

    await _do_settlement(update, context, closing)


async def cmd_setclosing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/setclosing 24500.50`", parse_mode="Markdown")
        return
    try:
        closing = float(context.args[0].replace(",", ""))
    except ValueError:
        await update.message.reply_text("❌ Invalid price.")
        return

    challenge = get_today_challenge()
    if not challenge:
        await update.message.reply_text("❌ No challenge today.")
        return
    await _do_settlement(update, context, closing)


async def _do_settlement(update, context, closing_price: float):
    challenge   = get_today_challenge()
    symbol      = challenge["symbol"]

    settle_challenge(closing_price)
    predictions = get_all_today_predictions()
    results     = []

    for pred in predictions:
        pts = calculate_points(pred["predicted_price"], closing_price)
        save_prediction_points(pred["id"], pts)
        add_points(pred["user_id"], pts)
        results.append({
            "user_id":    pred["user_id"],
            "first_name": pred["first_name"] or pred["username"] or "User",
            "predicted":  pred["predicted_price"],
            "points":     pts,
        })

    results.sort(key=lambda x: x["points"], reverse=True)

    # Broadcast top results
    result_text = (
        f"📊 *Results: {symbol}*\n"
        f"✅ Closing: *₹{closing_price}*\n\n"
        f"🏆 *Today's Top 5:*\n"
    )
    for i, r in enumerate(results[:5], 1):
        result_text += f"{medal(i)} {r['first_name']} — ₹{r['predicted']} → *{r['points']} pts*\n"
    result_text += f"\n📈 {len(predictions)} total predictions today!"

    await broadcast(context, result_text)

    # Personal notifications
    for pred in predictions:
        pts  = calculate_points(pred["predicted_price"], closing_price)
        diff = abs(pred["predicted_price"] - closing_price)
        emoji = "🎯" if pts == 1000 else "⭐" if pts >= 700 else "👍" if pts > 0 else "😔"
        try:
            await context.bot.send_message(
                chat_id=pred["user_id"],
                text=(
                    f"📊 *Your Result — {symbol}*\n\n"
                    f"Your guess:  *₹{pred['predicted_price']}*\n"
                    f"Closing:     *₹{closing_price}*\n"
                    f"Difference:  *₹{round(diff, 2)}*\n\n"
                    f"Points: *{pts}* {emoji}"
                ),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
        except Exception as e:
            logger.warning(f"Personal notify failed {pred['user_id']}: {e}")

    await update.message.reply_text(
        f"✅ Settled *{symbol}* @ ₹{closing_price}\n"
        f"Predictions processed: {len(predictions)}",
        parse_mode="Markdown"
    )


async def cmd_weeklyreward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    await do_weekly_reward(context)
    await update.message.reply_text("✅ Weekly reward triggered!")


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/broadcast <message>`", parse_mode="Markdown")
        return
    msg = " ".join(context.args)
    sent, failed = await broadcast(context, f"📢 {msg}")
    await update.message.reply_text(f"✅ Sent: {sent} | Failed: {failed}")


async def cmd_adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🔧 *Admin Commands:*\n\n"
        "/setstock <SYMBOL>    — Set today's stock + broadcast\n"
        "/settle               — Auto-fetch closing + settle\n"
        "/setclosing <price>   — Manual closing price + settle\n"
        "/weeklyreward         — Trigger weekly reward now\n"
        "/broadcast <msg>      — Message all users\n"
        "/adminhelp            — This help",
        parse_mode="Markdown"
    )

# ─── BROADCAST ───────────────────────────────────────

async def broadcast(context, message: str) -> tuple:
    user_ids        = get_all_user_ids()
    sent = failed   = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(
                chat_id=uid,
                text=message,
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Broadcast failed {uid}: {e}")
            failed += 1
    return sent, failed

# ─── WEEKLY REWARD ────────────────────────────────────

async def do_weekly_reward(context):
    today      = date.today()
    week_start = str(today - timedelta(days=today.weekday()))
    week_end   = str(today)
    top3       = get_weekly_leaderboard(3)

    if not top3:
        logger.info("No weekly data.")
        return

    announce = "🏆 *Weekly Results!*\n\n"
    for i, r in enumerate(top3, 1):
        stars = WEEKLY_PRIZES.get(i, 0)
        name  = r["first_name"] or r["username"] or "User"
        announce += (
            f"{medal(i)} *{name}*\n"
            f"   Points: *{r['weekly_points']}*\n"
            f"   Prize:  *{stars} ⭐ Stars*\n\n"
        )
        log_weekly_reward(week_start, week_end, i, r["user_id"],
                          r["username"], r["weekly_points"], stars)
        try:
            await context.bot.send_message(
                chat_id=r["user_id"],
                text=(
                    f"🎉 *Congratulations {name}!*\n\n"
                    f"You finished *#{i}* this week!\n"
                    f"Prize: *{stars} ⭐ Stars*\n\n"
                    "Stars will be sent by admin shortly. 🚀"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Winner notify failed {r['user_id']}: {e}")

    announce += "🔄 Weekly reset! Good luck next week 💪"
    await broadcast(context, announce)

    # Admin summary
    admin_msg = "⭐ *Send Stars to Winners:*\n\n"
    for i, r in enumerate(top3, 1):
        admin_msg += f"{medal(i)} `{r['user_id']}` — {WEEKLY_PRIZES.get(i,0)} Stars\n"
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
    except Exception:
        pass

    reset_weekly_points()
    logger.info("✅ Weekly rewards done!")

# ─── SCHEDULED JOBS ───────────────────────────────────

async def job_lock_predictions(context: ContextTypes.DEFAULT_TYPE):
    challenge = get_today_challenge()
    if challenge and not challenge["is_locked"]:
        lock_today_challenge()
        logger.info("✅ Locked predictions at 9 AM IST")
        await broadcast(
            context,
            f"🔒 *Predictions Locked!*\n\n"
            f"Stock: *{challenge['symbol']}*\n"
            "Market is open. Results after 3:30 PM IST 📊"
        )


async def job_settle_market(context: ContextTypes.DEFAULT_TYPE):
    challenge = get_today_challenge()
    if not challenge or challenge["is_settled"]:
        return

    symbol  = challenge["symbol"]
    closing = get_closing_price(symbol)

    if closing is None:
        logger.warning(f"Auto-settle failed for {symbol}")
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⚠️ Auto-settle failed for *{symbol}*.\nUse `/setclosing <price>`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        return

    settle_challenge(closing)
    predictions = get_all_today_predictions()
    results     = []

    for pred in predictions:
        pts = calculate_points(pred["predicted_price"], closing)
        save_prediction_points(pred["id"], pts)
        add_points(pred["user_id"], pts)
        results.append({
            "user_id":    pred["user_id"],
            "first_name": pred["first_name"] or pred["username"] or "User",
            "predicted":  pred["predicted_price"],
            "points":     pts,
        })

    results.sort(key=lambda x: x["points"], reverse=True)

    result_text = (
        f"📊 *Results: {symbol}*\n"
        f"✅ Closing: *₹{closing}*\n\n"
        f"🏆 *Today's Top 5:*\n"
    )
    for i, r in enumerate(results[:5], 1):
        result_text += f"{medal(i)} {r['first_name']} — ₹{r['predicted']} → *{r['points']} pts*\n"
    result_text += f"\n📈 {len(predictions)} predictions today!"

    await broadcast(context, result_text)

    for pred in predictions:
        pts  = calculate_points(pred["predicted_price"], closing)
        diff = abs(pred["predicted_price"] - closing)
        emoji = "🎯" if pts == 1000 else "⭐" if pts >= 700 else "👍" if pts > 0 else "😔"
        try:
            await context.bot.send_message(
                chat_id=pred["user_id"],
                text=(
                    f"📊 *Your Result — {symbol}*\n\n"
                    f"Guess:       *₹{pred['predicted_price']}*\n"
                    f"Closing:     *₹{closing}*\n"
                    f"Difference:  *₹{round(diff, 2)}*\n\n"
                    f"Points: *{pts}* {emoji}"
                ),
                parse_mode="Markdown",
                reply_markup=main_menu()
            )
        except Exception as e:
            logger.warning(f"Personal notify failed {pred['user_id']}: {e}")

    logger.info(f"✅ Auto-settled {symbol} @ ₹{closing}")


async def job_weekly_reward(context: ContextTypes.DEFAULT_TYPE):
    await do_weekly_reward(context)

# ─── MAIN ─────────────────────────────────────────────

def main():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # User commands
    app.add_handler(CommandHandler("start", start))

    # Admin commands
    app.add_handler(CommandHandler("setstock",     cmd_setstock))
    app.add_handler(CommandHandler("settle",       cmd_settle))
    app.add_handler(CommandHandler("setclosing",   cmd_setclosing))
    app.add_handler(CommandHandler("weeklyreward", cmd_weeklyreward))
    app.add_handler(CommandHandler("broadcast",    cmd_broadcast))
    app.add_handler(CommandHandler("adminhelp",    cmd_adminhelp))

    # Callbacks + text
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Scheduled jobs (UTC times)
    jq = app.job_queue

    # Lock at 9:00 AM IST = 3:30 AM UTC
    jq.run_daily(job_lock_predictions, time=time(3, 30, tzinfo=pytz.utc), name="lock")

    # Settle at 3:35 PM IST = 10:05 AM UTC
    jq.run_daily(job_settle_market, time=time(10, 5, tzinfo=pytz.utc), name="settle")

    # Weekly reward: Monday 12:00 AM IST = Sunday 6:30 PM UTC
    jq.run_daily(job_weekly_reward, time=time(18, 30, tzinfo=pytz.utc), days=(6,), name="weekly")

    logger.info("🚀 StockPredictor LIVE on Railway!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()