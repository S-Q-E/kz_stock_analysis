import os
import logging
import json
from openai import OpenAI
from datetime import datetime, timedelta
from dotenv import load_dotenv
from tradernet import Tradernet, TradernetSymbol as tns
from pandas import DataFrame
import pandas as pd

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from io import BytesIO
import matplotlib.pyplot as plt
import logging

# --- Логирование ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- Загружаем переменные окружения ---
load_dotenv()

PUBLIC_KEY = os.getenv("PUBLIC_KEY")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
API_TOKEN = os.getenv("TELEGRAM_API_KEY")

tn = Tradernet(PUBLIC_KEY, PRIVATE_KEY)


def get_history_df(ticker: str, period: str = None, start: str = None, end: str = None) -> DataFrame:
    """
    Получить исторические данные по тикеру в DataFrame.
    period: "1d", "1m", "6m", "1y" (если задан, перекрывает start/end)
    start, end: даты в формате YYYY-MM-DD
    """
    logger.info(f"Запрашиваю данные по тикеру {ticker}...")

    symbol = tns(ticker, tn).get_data()
    logger.info(f"Данные получены. Всего {len(symbol.candles)} свечей.")

    # Приводим timestamps к datetime64[ns]
    dates = pd.to_datetime(symbol.timestamps, unit='ms')

    market_data = pd.DataFrame(
        symbol.candles,
        index=dates,
        columns=["high", "low", "open", "close"]
    )

    if getattr(symbol, "volumes", None) is not None and len(symbol.volumes) > 0:
        market_data["volume"] = symbol.volumes
        logger.info("Добавлен столбец volume.")

    # --- Фильтрация по периодам ---
    if period:
        today = datetime.now()
        if period == "1d":
            start_date = today - timedelta(days=1)
        elif period == "1m":
            start_date = today - timedelta(days=30)
        elif period == "6m":
            start_date = today - timedelta(days=180)
        elif period == "1y":
            start_date = today - timedelta(days=365)
        else:
            raise ValueError("Неверный параметр period. Используй: 1d, 1m, 6m, 1y")

        market_data = market_data[market_data.index >= start_date]
        logger.info(f"Фильтр по периоду {period}: осталось {len(market_data)} записей.")

    # --- Фильтрация по start/end ---
    if start:
        market_data = market_data[market_data.index >= pd.to_datetime(start)]
    if end:
        market_data = market_data[market_data.index <= pd.to_datetime(end)]

    logger.info("DataFrame успешно сформирован.")
    return market_data


def analyze_with_openai(df, ticker: str, horizon: str = "1 month"):
    """
    Отправляем исторические данные в OpenAI для анализа и прогноза.
    Возвращает структурированный JSON с полями:
      trend, support, resistance, forecast, comment
    """
    # Берем последние 100 строк, чтобы не перегружать LLM
    last_data = df.tail(100).to_csv()

    logger.info(f"Отправляю данные по {ticker} в OpenAI для анализа (JSON-вывод)...")

    prompt = f"""
Я даю тебе исторические данные по акции {ticker}.
Данные содержат open, high, low, close, volume.

Вот последние котировки (CSV формат):
{last_data}

Проанализируй данные и сделай краткий прогноз по движению цены на {horizon}.
Ответ должен быть строго в JSON формате с такими ключами:
- trend: текущий тренд (например: "восходящий", "нисходящий", "флэт")
- support: список уровней поддержки (числа)
- resistance: список уровней сопротивления (числа)
- forecast: вероятное направление движения (текст)
- comment: краткий инвестиционный комментарий
"""

    response = client.chat.completions.create(
        model="gpt-5",
        messages=[
            {"role": "system", "content": "Ты опытный финансовый аналитик. Отвечай строго в формате JSON."},
            {"role": "user", "content": prompt}
        ],
        temperature=1
    )

    raw_output = response.choices[0].message.content.strip()
    logger.info("Анализ получен от OpenAI.")

    # Убираем кодовые блоки, если модель их добавила
    if raw_output.startswith("```"):
        raw_output = raw_output.strip("`")
        raw_output = raw_output.replace("json", "", 1).strip()

    try:
        result = json.loads(raw_output)
    except json.JSONDecodeError:
        logger.warning("Ответ не в JSON-формате, возвращаю как текст.")
        result = {"raw_text": raw_output}

    return result


def plot_with_levels(df, analysis, ticker: str):
    """
    Рисует график цены с уровнями поддержки, сопротивления и стрелкой прогноза до ближайшей цели.
    """
    plt.figure(figsize=(12, 6))

    # --- Цена
    plt.plot(df.index, df["close"], label="Цена закрытия", color="blue")

    # --- Поддержка
    if "support" in analysis:
        for level in analysis["support"]:
            plt.axhline(y=level, color="green", linestyle="--", alpha=0.7)
            plt.text(df.index[-1], level, f"Support {level}",
                     va="center", ha="left", fontsize=9, color="green")

    # --- Сопротивление
    if "resistance" in analysis:
        for level in analysis["resistance"]:
            plt.axhline(y=level, color="red", linestyle="--", alpha=0.7)
            plt.text(df.index[-1], level, f"Resistance {level}",
                     va="center", ha="left", fontsize=9, color="red")

    # --- Стрелка прогноза
    if "forecast" in analysis:
        last_date = df.index[-1]
        last_price = df["close"].iloc[-1]
        forecast_text = analysis["forecast"].lower()

        target_level = None
        arrow_color = "gray"

        if any(word in forecast_text for word in ["рост", "выше", "увелич", "повыш"]):
            # ищем ближайшее сопротивление выше текущей цены
            resistances = [lvl for lvl in analysis.get("resistance", []) if lvl > last_price]
            if resistances:
                target_level = min(resistances)  # ближайшее выше
                arrow_color = "green"
        elif any(word in forecast_text for word in ["паден", "ниже", "сниж", "коррекц"]):
            # ищем ближайшую поддержку ниже текущей цены
            supports = [lvl for lvl in analysis.get("support", []) if lvl < last_price]
            if supports:
                target_level = max(supports)  # ближайшее ниже
                arrow_color = "red"

        if target_level:
            plt.annotate(
                f"Прогноз: {target_level}",
                xy=(last_date, last_price),
                xytext=(last_date, target_level),
                arrowprops=dict(facecolor=arrow_color, shrink=0.05, width=2, headwidth=8),
                ha="center", fontsize=10, color=arrow_color
            )

    # --- Оформление
    plt.title(f"Анализ {ticker} — тренд: {analysis.get('trend', 'неизвестно')}")
    plt.xlabel("Дата")
    plt.ylabel("Цена")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()


