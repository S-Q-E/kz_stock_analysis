from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from io import BytesIO
import matplotlib.pyplot as plt
import logging
import os
from dotenv import load_dotenv
import asyncio

from datetime import datetime, timedelta

from app.tradernet import get_history_df
from app.ai import analyze_with_openai
from app.plot import plot_with_levels
from app.db import connect_db, close_db, add_favorite, remove_favorite, get_favorites, is_favorite
from app.models import User, Request, Graph

# --- Старт
from aiogram import types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.types import ReplyKeyboardRemove, BufferedInputFile
from aiogram.filters.callback_data import CallbackData


class TickerCallback(CallbackData, prefix="ticker"):
    action: str
    ticker: str

class FavoriteCallback(CallbackData, prefix="fav"):
    action: str
    ticker: str

# --- Логирование ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_API_KEY")


bot = Bot(token=API_TOKEN)
dp = Dispatcher()

user_data = {}  # храним тикер и выбранный период

class TickerState(StatesGroup):
    waiting_for_ticker = State()
    waiting_for_period = State()


async def get_or_create_user(message: types.Message):
    connect_db()
    user, created = User.get_or_create(
        id=message.from_user.id,
        defaults={
            'username': message.from_user.username,
            'first_name': message.from_user.first_name,
            'last_name': message.from_user.last_name
        }
    )
    close_db()
    return user

# старт — переводим в состояние ожидания тикера
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user = await get_or_create_user(message)
    logger.info(f"User {user.id} ({user.username}) started the bot.")
    await state.set_state(TickerState.waiting_for_ticker)
    await message.reply("Привет! Отправь тикер, и я дам анализ с графиком. Используй /favorites для просмотра избранных.")

# принимаем тикер — переводим в состояние ожидания периода
@dp.message(TickerState.waiting_for_ticker)
async def ticker_handler(message: types.Message, state: FSMContext):
    ticker = message.text.strip().upper()
    user_data[message.from_user.id] = {"ticker": ticker}

    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="1д"), types.KeyboardButton(text="1м"), types.KeyboardButton(text="6м"))
    builder.row(types.KeyboardButton(text="1г"), types.KeyboardButton(text="всё"))
    keyboard = builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

    await message.reply(f"Выберите период анализа для {ticker}:" , reply_markup=keyboard)
    await state.set_state(TickerState.waiting_for_period)


@dp.message(TickerState.waiting_for_period, F.text.in_(["1д", "1м", "6м", "1г", "всё"]))
async def period_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    period_map = {"1д": "1d", "1м": "1m", "6м": "6m", "1г": "1y", "всё": "all"}
    period = period_map[message.text]

    ticker = user_data.get(user_id, {}).get("ticker")
    if not ticker:
        await message.reply("Ошибка: тикер не найден. Отправьте тикер заново.")
        await state.set_state(TickerState.waiting_for_ticker)
        return

    await message.reply(f"Запрашиваю данные по {ticker} за период {period}...", reply_markup=ReplyKeyboardRemove())

    user_db = await get_or_create_user(message) # Ensure user exists in DB

    df = None
    analysis = None
    graph_filepath = None
    buf = None
    
    try:
        connect_db()
        # Check if a similar request exists in the last 24 hours
        one_day_ago = datetime.now() - timedelta(days=1)
        cached_request = Request.select().where(
            (Request.user == user_db) &
            (Request.ticker == ticker) &
            (Request.period == period) &
            (Request.request_date >= one_day_ago)
        ).order_by(Request.request_date.desc()).first()

        if cached_request:
            logger.info(f"Using cached analysis for {ticker} ({period}). Request ID: {cached_request.id}")
            analysis = {
                "trend": cached_request.trend,
                "forecast": cached_request.forecast,
                "comment": cached_request.comment
            }
            # Retrieve graph if available
            cached_graph = Graph.select().where(Graph.request == cached_request).first()
            if cached_graph and os.path.exists(cached_graph.filepath):
                graph_filepath = cached_graph.filepath
                with open(graph_filepath, "rb") as f:
                    buf = BytesIO(f.read())
                await message.reply(f"📈 Кэшированный анализ по {ticker} (за {cached_request.request_date.strftime('%Y-%m-%d %H:%M:%S')}):")
            else:
                await message.reply(f"📈 Кэшированный анализ по {ticker} (за {cached_request.request_date.strftime('%Y-%m-%d %H:%M:%S')}), график не найден.")
            
        if not analysis: # If no cached analysis or graph, process new request
            df = get_history_df(ticker, period=period)
            if df.empty:
                await message.reply(f"Не удалось получить исторические данные для тикера **{ticker}** за этот период. Попробуйте другой тикер или период.")
                await state.clear()
                return

            analysis = analyze_with_openai(df, ticker, horizon=period)

            # Save request to database
            request_db = Request.create(
                user=user_db,
                ticker=ticker,
                period=period,
                trend=analysis.get('trend'),
                forecast=analysis.get('forecast'),
                comment=analysis.get('comment')
            )

            buf = BytesIO()
            plot_with_levels(df, analysis, ticker)
            plt.savefig(buf, format="png")
            buf.seek(0)
            plt.close()

            # Save graph to file
            if not os.path.exists("graphs"):
                os.makedirs("graphs")
            graph_filename = f"graphs/{ticker}_{period}_{request_db.id}.png"
            with open(graph_filename, "wb") as f:
                f.write(buf.getvalue())
            
            Graph.create(
                request=request_db,
                filepath=graph_filename
            )
            graph_filepath = graph_filename


    except Exception as e:
        logger.error(f"Error processing request for {ticker} ({period}): {e}")
        await message.reply(f"Произошла ошибка при обработке запроса для {ticker}: {e}")
    finally:
        close_db()
        await state.clear() # Clear state regardless of success or failure

    if analysis and graph_filepath:
        # Build keyboard with favorite toggle
        builder = InlineKeyboardBuilder()
        is_fav = is_favorite(user_id, ticker)
        if is_fav:
            builder.button(text="🌟Удалить из избранного", callback_data=FavoriteCallback(action="remove", ticker=ticker).pack())
        else:
            builder.button(text="⭐Добавить в избранное", callback_data=FavoriteCallback(action="add", ticker=ticker).pack())
        
        await message.reply(
            f"Анализ по {ticker}:\n"
            f"Тренд: {analysis.get('trend')}\n"
            f"Прогноз: {analysis.get('forecast')}\n"
            f"Комментарий: {analysis.get('comment')}",
            reply_markup=builder.as_markup()
        )
        if buf:
            buf.seek(0)
            await bot.send_photo(message.chat.id, BufferedInputFile(buf.getvalue(), filename=f"{ticker}.png"))
        else: # Resend from file if it was a cached request
            with open(graph_filepath, "rb") as f:
                buf = BytesIO(f.read())
            await bot.send_photo(message.chat.id, BufferedInputFile(buf.getvalue(), filename=f"{ticker}.png"))


@dp.callback_query(FavoriteCallback.filter(F.action == "add"))
async def add_to_favorites_handler(query: types.CallbackQuery, callback_data: FavoriteCallback):
    user_id = query.from_user.id
    ticker = callback_data.ticker
    if add_favorite(user_id, ticker):
        await query.answer(f"{ticker} добавлен в избранное!")
        # Update the keyboard
        builder = InlineKeyboardBuilder()
        builder.button(text="🌟Удалить из избранного", callback_data=FavoriteCallback(action="remove", ticker=ticker).pack())
        await query.message.edit_reply_markup(reply_markup=builder.as_markup())
    else:
        await query.answer(f"{ticker} уже был в избранном.")

@dp.callback_query(FavoriteCallback.filter(F.action == "remove"))
async def remove_from_favorites_handler(query: types.CallbackQuery, callback_data: FavoriteCallback):
    user_id = query.from_user.id
    ticker = callback_data.ticker
    if remove_favorite(user_id, ticker):
        await query.answer(f"{ticker} удален из избранного!")
        # Update the keyboard
        builder = InlineKeyboardBuilder()
        builder.button(text="⭐Добавить в избранное", callback_data=FavoriteCallback(action="add", ticker=ticker).pack())
        await query.message.edit_reply_markup(reply_markup=builder.as_markup())
    else:
        await query.answer(f"Не удалось удалить {ticker} из избранного.")


@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    user_db = await get_or_create_user(message)
    connect_db()
    requests = Request.select().where(Request.user == user_db).order_by(Request.request_date.desc()).limit(5)
    close_db()

    if not requests:
        await message.reply("У вас пока нет истории запросов.")
        return

    response_text = "Ваши последние запросы:\n\n"
    for req in requests:
        response_text += (
            f"📊 Тикер: {req.ticker}\n"
            f"⏱ Период: {req.period}\n"
            f"📈 Тренд: {req.trend or 'N/A'}\n"
            f"💬 Комментарий: {req.comment or 'N/A'}\n"
            f"📅 Дата: {req.request_date.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )
    
    await message.reply(response_text)

@dp.message(Command("favorites"))
async def cmd_favorites(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    favorites = get_favorites(user_id)

    if not favorites:
        await message.reply("У вас пока нет избранных тикеров. Вы можете добавить их после анализа.")
        return

    builder = InlineKeyboardBuilder()
    for ticker in favorites:
        builder.button(text=ticker, callback_data=TickerCallback(action="select", ticker=ticker).pack())
    
    builder.adjust(3) # 3 buttons per row
    await message.reply("Ваши избранные тикеры. Нажмите на любой, чтобы выбрать период для анализа:", reply_markup=builder.as_markup())

@dp.callback_query(TickerCallback.filter(F.action == "select"))
async def select_favorite_ticker_handler(query: types.CallbackQuery, callback_data: TickerCallback, state: FSMContext):
    ticker = callback_data.ticker
    user_data[query.from_user.id] = {"ticker": ticker}

    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="1д"), types.KeyboardButton(text="1м"), types.KeyboardButton(text="6м"))
    builder.row(types.KeyboardButton(text="1г"), types.KeyboardButton(text="всё"))
    keyboard = builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

    await query.message.answer(f"Выберите период анализа для {ticker}:" , reply_markup=keyboard)
    await query.answer() # Close the inline keyboard
    await state.set_state(TickerState.waiting_for_period)


async def main():
    await dp.start_polling(bot)

