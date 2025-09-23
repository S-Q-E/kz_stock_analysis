from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from io import BytesIO
import matplotlib.pyplot as plt
import logging
import os
from dotenv import load_dotenv
import asyncio


from app import get_history_df, analyze_with_openai, plot_with_levels

load_dotenv()

API_TOKEN = os.getenv("TELEGRAM_API_KEY")


bot = Bot(token=API_TOKEN)
dp = Dispatcher()
logging.basicConfig(level=logging.INFO)

user_data = {}  # храним тикер и выбранный период

# --- Старт
from aiogram import types, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from aiogram.types import ReplyKeyboardRemove, BufferedInputFile


class TickerState(StatesGroup):
    waiting_for_ticker = State()
    waiting_for_period = State()

# старт — переводим в состояние ожидания тикера
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.set_state(TickerState.waiting_for_ticker)
    await message.reply("Привет! Отправь тикер, и я дам анализ с графиком.")

# принимаем тикер — переводим в состояние ожидания периода
@dp.message(TickerState.waiting_for_ticker)
async def ticker_handler(message: types.Message, state: FSMContext):
    ticker = message.text.strip().upper()
    user_data[message.from_user.id] = {"ticker": ticker}

    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="1д"), types.KeyboardButton(text="1м"), types.KeyboardButton(text="6м"))
    builder.row(types.KeyboardButton(text="1г"), types.KeyboardButton(text="всё"))
    keyboard = builder.as_markup(resize_keyboard=True, one_time_keyboard=True)

    await message.reply(f"Выберите период анализа для {ticker}:", reply_markup=keyboard)
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

    # --- Добавляем проверку здесь ---
    df = get_history_df(ticker, period=period)
    if df.empty:
        await message.reply(f"Не удалось получить исторические данные для тикера **{ticker}** за этот период. Попробуйте другой тикер или период.")
        await state.clear()
        return

    # --- Твой код анализа/построения графика ---
    analysis = analyze_with_openai(df, ticker, horizon=period)

    buf = BytesIO()
    plot_with_levels(df, analysis, ticker)
    plt.savefig(buf, format="png")
    buf.seek(0)

    plt.close()

    await message.reply(
        f"Анализ по {ticker}:\n"
        f"Тренд: {analysis.get('trend')}\n"
        f"Прогноз: {analysis.get('forecast')}\n"
        f"Комментарий: {analysis.get('comment')}"
    )
    await bot.send_photo(message.chat.id, BufferedInputFile(buf.getvalue(), filename=f"{ticker}.png"))
    # очищаем состояние — следующий ввод будет новым тикером
    await state.clear()


async def main():
    bot = Bot(token=API_TOKEN)

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

