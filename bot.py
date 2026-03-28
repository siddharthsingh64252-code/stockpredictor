import logging
import os
import pytz
from datetime import datetime, timedelta
from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler,
    PreCheckoutQueryHandler
)

from database import (
    init_db, add_user, get_user, is_premium, is_banned,
    set_premium, remove_premium, ban_user, unban_user,
    get_predictions_today, has_predicted_stock_today,
    add_prediction, get_user_predictions_today,
    get_all_predictions_for_date, evaluate_prediction,
    update_user_points, get_weekly_leaderboard,
    get_user_weekly_rank, reset_weekly_points,
    save_weekly_winners, get_all_user_ids,
    get_all_users, get_stats
)

from market import (
    get_all_closing_prices, is_market_open,
    is_prediction_window_open, get_next_trading_date,
    calculate_points, STOCKS
)

load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 6845468120
IST = pytz.timezone("Asia/Kolkata")
PREMIUM_STARS = 50

user_state = {}
admin_broadcast_mode = {}

# -------------------- KEYBOARDS --------------------

def main_menu_keyboard(user_id):
    premium = is_premium(user_id)
    plan = "Premium" if premium else "Free"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Predict Today", callback_data="predict"),
            InlineKeyboardButton("My Predictions", callback_data="mypredictions"),
        ],
        [
            InlineKeyboardButton("Leaderboard", callback_data="leaderboard"),
            InlineKeyboardButton("My Rank", callback_data="myrank"),
        ],
        [
            InlineKeyboardButton("How to Play", callback_data="howtoplay"),
            InlineKeyboardButton(f"Plan: {plan}", callback_data="premium"),
        ],
    ])

def back_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Back to Menu", callback_data="menu_main")]
    ])

def stock_keyboard(user_id, prediction_date):
    buttons = []
    for symbol in STOCKS:
        already = has_predicted_stock_today(user_id, symbol, prediction_date)
        label = f"{symbol} (done)" if already else symbol
        buttons.append([InlineKeyboardButton(label, callback_data=f"stock_{symbol}")])
    buttons.append([InlineKeyboardButton("Cancel", callback_data="menu_main")])
    return InlineKeyboardMarkup(buttons)

# -------------------- START --------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name, user.last_name)

    if is_banned(user.id):
        await update.message.reply_text("You are banned from StockTap.")
        return

    premium = is_premium(user.id)
    market_open = is_market_open()
    next_date = get_next_trading_date()

    if market_open:
        status = "Market is LIVE - No predictions accepted now"
    else:
        status = f"Prediction window OPEN for {next_date}"

    plan = "PREMIUM - 2 predictions/day" if premium else "FREE - 1 prediction/day"

    await update.message.reply_text(
        f"Welcome to StockTap!\n\n"
        f"Predict NSE closing prices and win Stars!\n\n"
        f"Status: {status}\n"
        f"Plan: {plan}\n\n"
        f"How it works:\n"
        f"Predict closing price of NIFTY, BANKNIFTY or SENSEX\n"
        f"Closer your prediction = More points\n"
        f"Top 3 weekly winners get Telegram Stars!\n\n"
        f"Choose an option:",
        reply_markup=main_menu_keyboard(user.id)
    )

# -------------------- CALLBACKS --------------------

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if is_banned(user_id):
        await query.edit_message_text("You are banned from StockTap.")
        return

    # MAIN MENU
    if data == "menu_main":
        premium = is_premium(user_id)
        market_open = is_market_open()
        next_date = get_next_trading_date()

        if market_open:
            status = "Market is LIVE - No predictions accepted"
        else:
            status = f"Prediction window OPEN for {next_date}"

        plan = "PREMIUM - 2 predictions/day" if premium else "FREE - 1 prediction/day"

        await query.edit_message_text(
            f"StockTap Main Menu\n\n"
            f"Status: {status}\n"
            f"Plan: {plan}\n\n"
            f"Choose an option:",
            reply_markup=main_menu_keyboard(user_id)
        )

    # PREDICT
    elif data == "predict":
        if is_market_open():
            await query.edit_message_text(
                "Market is currently OPEN!\n\n"
                "No predictions accepted during market hours.\n"
                "Market closes at 3:30 PM IST.\n\n"
                "Come back after 3:30 PM to predict tomorrow!",
                reply_markup=back_keyboard()
            )
            return

        next_date = get_next_trading_date()
        premium = is_premium(user_id)
        limit = 2 if premium else 1
        used = get_predictions_today(user_id, next_date)

        if used >= limit:
            plan = "Premium (2/day)" if premium else "Free (1/day)"
            await query.edit_message_text(
                f"You have used all your predictions for today!\n\n"
                f"Plan: {plan}\n"
                f"Used: {used}/{limit}\n\n"
                f"Upgrade to Premium for 2 predictions/day!\n"
                f"Use /premium to upgrade.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Get Premium", callback_data="premium")],
                    [InlineKeyboardButton("Back to Menu", callback_data="menu_main")]
                ])
            )
            return

        remaining = limit - used
        await query.edit_message_text(
            f"Select stock to predict for {next_date}:\n\n"
            f"Predictions remaining: {remaining}/{limit}\n\n"
            f"Already predicted stocks are marked (done):",
            reply_markup=stock_keyboard(user_id, next_date)
        )

    # STOCK SELECTED
    elif data.startswith("stock_"):
        if is_market_open():
            await query.edit_message_text(
                "Market is open! No predictions accepted.",
                reply_markup=back_keyboard()
            )
            return

        symbol = data.replace("stock_", "")
        next_date = get_next_trading_date()

        if has_predicted_stock_today(user_id, symbol, next_date):
            await query.edit_message_text(
                f"You already predicted {symbol} for {next_date}!\n\n"
                f"Choose a different stock.",
                reply_markup=stock_keyboard(user_id, next_date)
            )
            return

        user_state[user_id] = {
            "step": "waiting_price",
            "symbol": symbol,
            "date": next_date
        }

        await query.edit_message_text(
            f"Enter your predicted closing price for {symbol}\n\n"
            f"Date: {next_date}\n\n"
            f"Type the price below (numbers only)\n"
            f"Example: 22500 or 22500.50"
        )

    # MY PREDICTIONS
    elif data == "mypredictions":
        next_date = get_next_trading_date()
        predictions = get_user_predictions_today(user_id, next_date)

        if not predictions:
            await query.edit_message_text(
                f"No predictions yet for {next_date}!\n\n"
                f"Market is {'OPEN - wait till 3:30 PM' if is_market_open() else 'CLOSED - predict now!'}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Predict Now", callback_data="predict")],
                    [InlineKeyboardButton("Back to Menu", callback_data="menu_main")]
                ])
            )
            return

        text = f"Your predictions for {next_date}:\n\n"
        for p in predictions:
            status = "Evaluated" if p["is_evaluated"] else "Pending result"
            points = f"{p['points_earned']} pts" if p["is_evaluated"] else "Waiting..."
            text += (
                f"Stock: {p['stock_symbol']}\n"
                f"Your prediction: Rs {p['predicted_price']}\n"
                f"Actual price: {'Rs ' + str(p['actual_price']) if p['actual_price'] else 'Not yet'}\n"
                f"Points: {points}\n"
                f"Status: {status}\n\n"
            )

        await query.edit_message_text(
            text,
            reply_markup=back_keyboard()
        )

    # LEADERBOARD
    elif data == "leaderboard":
        leaders = get_weekly_leaderboard()

        if not leaders:
            await query.edit_message_text(
                "No predictions made this week yet!\n\n"
                "Be the first to predict!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Predict Now", callback_data="predict")],
                    [InlineKeyboardButton("Back to Menu", callback_data="menu_main")]
                ])
            )
            return

        text = "Weekly Leaderboard\n\n"
        medals = ["1", "2", "3"]
        for i, leader in enumerate(leaders):
            name = leader["first_name"] or leader["username"] or "Unknown"
            username = f"@{leader['username']}" if leader["username"] else ""
            medal = medals[i] if i < 3 else str(i + 1)
            text += f"{medal}. {name} {username}\n"
            text += f"   Points: {round(leader['weekly_points'], 2)}\n\n"

        text += "\nTop 3 win Telegram Stars every Sunday!"

        user_rank = get_user_weekly_rank(user_id)
        user = get_user(user_id)
        text += f"\nYour rank: #{user_rank}"
        text += f"\nYour points: {round(user['weekly_points'], 2)}"

        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Predict Now", callback_data="predict")],
                [InlineKeyboardButton("Back to Menu", callback_data="menu_main")]
            ])
        )

    # MY RANK
    elif data == "myrank":
        user = get_user(user_id)
        rank = get_user_weekly_rank(user_id)
        next_date = get_next_trading_date()
        predictions_today = get_predictions_today(user_id, next_date)
        premium = is_premium(user_id)
        limit = 2 if premium else 1

        await query.edit_message_text(
            f"Your Stats\n\n"
            f"Weekly rank: #{rank}\n"
            f"Weekly points: {round(user['weekly_points'], 2)}\n"
            f"Total points: {round(user['total_points'], 2)}\n"
            f"Total predictions: {user['predictions_made']}\n\n"
            f"Today: {predictions_today}/{limit} predictions used\n"
            f"Plan: {'Premium' if premium else 'Free'}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("View Leaderboard", callback_data="leaderboard")],
                [InlineKeyboardButton("Back to Menu", callback_data="menu_main")]
            ])
        )

    # HOW TO PLAY
    elif data == "howtoplay":
        await query.edit_message_text(
            "How to Play StockTap\n\n"
            "1. Market closes at 3:30 PM\n"
            "2. Predict tomorrow's closing price\n"
            "   for NIFTY, BANKNIFTY or SENSEX\n"
            "3. Predictions accepted until 9:14 AM\n"
            "4. Market opens 9:15 AM - no more predictions\n"
            "5. Results announced at 3:31 PM\n\n"
            "Points System:\n"
            "Perfect prediction = 100 points\n"
            "0.5% off = 90 points\n"
            "1% off = 80 points\n"
            "2% off = 60 points\n"
            "5%+ off = 0 points\n\n"
            "Weekly Prizes:\n"
            "Rank 1 = 100 Telegram Stars\n"
            "Rank 2 = 50 Telegram Stars\n"
            "Rank 3 = 25 Telegram Stars\n\n"
            "Free plan: 1 prediction/day\n"
            "Premium plan: 2 predictions/day + 1.5x points",
            reply_markup=back_keyboard()
        )

    # PREMIUM
    elif data == "premium":
        if is_premium(user_id):
            await query.edit_message_text(
                "You are already a Premium member!\n\n"
                "Enjoying 2 predictions/day and 1.5x points!",
                reply_markup=back_keyboard()
            )
            return

        await query.edit_message_text(
            "StockTap Premium\n\n"
            "Free plan:\n"
            "- 1 prediction per day\n"
            "- Normal points\n\n"
            "Premium plan (50 Stars):\n"
            "- 2 predictions per day\n"
            "- 1.5x points multiplier\n"
            "- Priority results notification\n\n"
            "One time payment - 50 Telegram Stars\n\n"
            "Click below to upgrade:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Pay 50 Stars", callback_data="pay_premium")],
                [InlineKeyboardButton("Back to Menu", callback_data="menu_main")]
            ])
        )

    elif data == "pay_premium":
        await context.bot.send_invoice(
            chat_id=query.from_user.id,
            title="StockTap Premium",
            description="2 predictions/day + 1.5x points multiplier",
            payload="stocktap_premium",
            currency="XTR",
            prices=[LabeledPrice("Premium Plan", PREMIUM_STARS)],
        )

# -------------------- MESSAGE HANDLER --------------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if is_banned(user_id):
        await update.message.reply_text("You are banned from StockTap.")
        return

    # ADMIN BROADCAST
    if user_id == ADMIN_ID and admin_broadcast_mode.get(ADMIN_ID):
        admin_broadcast_mode.pop(ADMIN_ID, None)
        user_ids = get_all_user_ids()
        success = 0
        failed = 0
        await update.message.reply_text(f"Broadcasting to {len(user_ids)} users...")
        for uid in user_ids:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"Message from StockTap:\n\n{text}"
                )
                success += 1
            except Exception:
                failed += 1
        await update.message.reply_text(
            f"Broadcast done!\nSent: {success}\nFailed: {failed}"
        )
        return

    # PREDICTION PRICE INPUT
    if user_id in user_state and user_state[user_id].get("step") == "waiting_price":
        if is_market_open():
            user_state.pop(user_id, None)
            await update.message.reply_text(
                "Market is open! No predictions accepted.",
                reply_markup=main_menu_keyboard(user_id)
            )
            return

        try:
            predicted_price = float(text.replace(",", ""))
        except ValueError:
            await update.message.reply_text(
                "Invalid price! Enter numbers only.\nExample: 22500 or 22500.50"
            )
            return

        state = user_state[user_id]
        symbol = state["symbol"]
        prediction_date = state["date"]

        # Double check limit
        premium = is_premium(user_id)
        limit = 2 if premium else 1
        used = get_predictions_today(user_id, prediction_date)

        if used >= limit:
            user_state.pop(user_id, None)
            await update.message.reply_text(
                f"You have used all {limit} predictions for today!",
                reply_markup=main_menu_keyboard(user_id)
            )
            return

        add_prediction(user_id, symbol, predicted_price, prediction_date)
        user_state.pop(user_id, None)

        remaining = limit - used - 1
        premium = is_premium(user_id)

        await update.message.reply_text(
            f"Prediction saved!\n\n"
            f"Stock: {symbol}\n"
            f"Your prediction: Rs {predicted_price}\n"
            f"Date: {prediction_date}\n\n"
            f"Predictions remaining today: {remaining}/{limit}\n\n"
            f"Results announced at 3:31 PM IST!\n"
            f"Good luck!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Predict Another", callback_data="predict")] if remaining > 0 else
                [InlineKeyboardButton("View Leaderboard", callback_data="leaderboard")],
                [InlineKeyboardButton("My Predictions", callback_data="mypredictions")],
                [InlineKeyboardButton("Main Menu", callback_data="menu_main")]
            ])
        )
        return

    # DEFAULT
    await update.message.reply_text(
        "Use the menu to get started:",
        reply_markup=main_menu_keyboard(user_id)
    )

# -------------------- PAYMENT --------------------

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    if query.invoice_payload == "stocktap_premium":
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Something went wrong!")

async def payment_success(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    set_premium(user_id)
    await update.message.reply_text(
        "Payment successful!\n\n"
        "You are now a StockTap Premium member!\n\n"
        "2 predictions/day + 1.5x points activated!",
        reply_markup=main_menu_keyboard(user_id)
    )

# -------------------- SCHEDULED JOBS --------------------

async def announce_results(context):
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return

    if not (now.hour == 15 and now.minute >= 31):
        return

    prices = get_all_closing_prices()
    if not prices:
        print("Could not fetch closing prices")
        return

    today = now.date()
    predictions = get_all_predictions_for_date(today)

    if not predictions:
        return

    results_text = (
        f"StockTap Results - {today}\n\n"
        f"Actual Closing Prices:\n"
    )
    for symbol, price in prices.items():
        results_text += f"{symbol}: Rs {price}\n"
    results_text += "\nCalculating your points now..."

    user_ids = get_all_user_ids()
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=results_text)
        except Exception:
            pass

    for prediction in predictions:
        symbol = prediction["stock_symbol"]
        actual = prices.get(symbol)
        if not actual:
            continue

        predicted = prediction["predicted_price"]
        points = calculate_points(predicted, actual)

        premium = is_premium(prediction["user_id"])
        if premium:
            points = round(points * 1.5, 2)

        evaluate_prediction(prediction["id"], actual, points)
        update_user_points(prediction["user_id"], points)

        try:
            await context.bot.send_message(
                chat_id=prediction["user_id"],
                text=(
                    f"Your Result for {symbol}:\n\n"
                    f"Your prediction: Rs {predicted}\n"
                    f"Actual closing: Rs {actual}\n"
                    f"Points earned: {points}\n\n"
                    f"{'1.5x Premium bonus applied!' if premium else ''}\n"
                    f"Check leaderboard to see your rank!"
                ),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("View Leaderboard", callback_data="leaderboard")]
                ])
            )
        except Exception as e:
            print(f"Error sending result to {prediction['user_id']}: {e}")

async def weekly_reset(context):
    now = datetime.now(IST)
    if now.weekday() != 6 or now.hour != 20:
        return

    leaders = get_weekly_leaderboard()

    if not leaders:
        return

    week_end = now.date()
    week_start = week_end - timedelta(days=6)
    save_weekly_winners(week_start, week_end, leaders)

    announcement = "Weekly Results!\n\nTop 3 winners this week:\n\n"
    prizes = [100, 50, 25]
    medals = ["1st", "2nd", "3rd"]

    for i, leader in enumerate(leaders[:3]):
        name = leader["first_name"] or leader["username"] or "Unknown"
        username = f"@{leader['username']}" if leader["username"] else ""
        announcement += (
            f"{medals[i]}: {name} {username}\n"
            f"Points: {round(leader['weekly_points'], 2)}\n"
            f"Prize: {prizes[i]} Telegram Stars\n\n"
        )

    announcement += (
        "Winners will receive their Stars shortly!\n\n"
        "New week starts now - predict again!"
    )

    user_ids = get_all_user_ids()
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=announcement)
        except Exception:
            pass

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"Weekly reset done!\n\n"
            f"Send Stars to winners manually:\n\n"
            + "\n".join([
                f"{medals[i]}: {leaders[i]['user_id']} "
                f"(@{leaders[i]['username']}) - {prizes[i]} Stars"
                for i in range(min(3, len(leaders)))
            ])
        )
    )

    reset_weekly_points()

# -------------------- ADMIN COMMANDS --------------------

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Unknown command.")
        return
    stats = get_stats()
    await update.message.reply_text(
        f"StockTap Stats\n\n"
        f"Total users: {stats['total_users']}\n"
        f"Premium users: {stats['premium_users']}\n"
        f"Free users: {stats['free_users']}\n"
        f"Total predictions: {stats['total_predictions']}\n"
        f"New today: {stats['new_today']}"
    )

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Unknown command.")
        return
    users = get_all_users()
    text = f"All Users ({len(users)}):\n\n"
    for u in users[:20]:
        username = f"@{u['username']}" if u['username'] else "No username"
        plan = "PREMIUM" if u['is_premium'] else "FREE"
        banned = " BANNED" if u['is_banned'] else ""
        text += (
            f"ID: {u['user_id']}\n"
            f"Name: {u['first_name']} ({username})\n"
            f"Plan: {plan}{banned}\n"
            f"Weekly pts: {round(u['weekly_points'], 2)}\n\n"
        )
    if len(users) > 20:
        text += f"...and {len(users) - 20} more"
    await update.message.reply_text(text)

async def admin_makepremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Unknown command.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /makepremium <user_id>")
        return
    try:
        target_id = int(context.args[0])
        set_premium(target_id)
        await update.message.reply_text(f"User {target_id} is now Premium!")
        await context.bot.send_message(
            chat_id=target_id,
            text="You have been upgraded to Premium by admin!\n2 predictions/day + 1.5x points!"
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def admin_removepremium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Unknown command.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /removepremium <user_id>")
        return
    try:
        target_id = int(context.args[0])
        remove_premium(target_id)
        await update.message.reply_text(f"Premium removed from {target_id}.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Unknown command.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /ban <user_id>")
        return
    try:
        target_id = int(context.args[0])
        ban_user(target_id)
        await update.message.reply_text(f"User {target_id} banned.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Unknown command.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /unban <user_id>")
        return
    try:
        target_id = int(context.args[0])
        unban_user(target_id)
        await update.message.reply_text(f"User {target_id} unbanned.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def admin_broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Unknown command.")
        return
    admin_broadcast_mode[ADMIN_ID] = True
    await update.message.reply_text(
        "Broadcast mode ON\n\nType your message to send to all users.\n"
        "Type /cancelbroadcast to cancel."
    )

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    admin_broadcast_mode.pop(ADMIN_ID, None)
    await update.message.reply_text("Broadcast cancelled.")

async def admin_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Unknown command.")
        return
    leaders = get_weekly_leaderboard()
    if not leaders:
        await update.message.reply_text("No leaders yet.")
        return
    text = "Current Weekly Leaderboard:\n\n"
    for i, l in enumerate(leaders):
        text += (
            f"{i+1}. {l['first_name']} (@{l['username']})\n"
            f"   ID: {l['user_id']}\n"
            f"   Points: {round(l['weekly_points'], 2)}\n\n"
        )
    await update.message.reply_text(text)

# -------------------- MAIN --------------------

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    # Admin commands
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("users", admin_users))
    app.add_handler(CommandHandler("makepremium", admin_makepremium))
    app.add_handler(CommandHandler("removepremium", admin_removepremium))
    app.add_handler(CommandHandler("ban", admin_ban))
    app.add_handler(CommandHandler("unban", admin_unban))
    app.add_handler(CommandHandler("broadcast", admin_broadcast_cmd))
    app.add_handler(CommandHandler("cancelbroadcast", cancel_broadcast))
    app.add_handler(CommandHandler("adminleaderboard", admin_leaderboard))

    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payment_success))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Check results every minute
    app.job_queue.run_repeating(announce_results, interval=60, first=10)

    # Weekly reset check every hour
    app.job_queue.run_repeating(weekly_reset, interval=3600, first=30)

    print("StockTap is LIVE!")
    app.run_polling()

if __name__ == "__main__":
    main()