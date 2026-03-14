import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from tradernet import Tradernet, TradernetSymbol as tns
from pandas import DataFrame
import pandas as pd

# --- Логирование ---
logger = logging.getLogger(__name__)

# --- Загружаем переменные окружения ---
load_dotenv()

PUBLIC_KEY = os.getenv("PUBLIC_KEY")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

tn = Tradernet(PUBLIC_KEY, PRIVATE_KEY)


def get_history_df(ticker: str, period: str = None, start: str = None, end: str = None) -> DataFrame:
    logger.info(f"Запрашиваю данные по тикеру {ticker}...")

    symbol = tns(ticker, tn).get_data()

    # --- Проверка на наличие данных ---
    timestamps = getattr(symbol, "timestamps", [])
    candles = getattr(symbol, "candles", [])

    if timestamps is None or len(timestamps) == 0 or candles is None or len(candles) == 0:
        logger.warning(f"Нет данных по тикеру {ticker}")
        return pd.DataFrame()

    logger.info(f"Данные получены. Всего {len(candles)} свечей.")

    # --- Универсальная обработка timestamps ---
    if isinstance(timestamps[0], (int, float)):
        dates = pd.to_datetime(timestamps, unit="ms", errors="coerce")
    else:
        dates = pd.to_datetime(timestamps, errors="coerce")

    market_data = pd.DataFrame(
        candles,
        index=dates,
        columns=["high", "low", "open", "close"]
    )

    if getattr(symbol, "volumes", None) is not None and len(symbol.volumes) > 0:
        market_data["volume"] = symbol.volumes
        logger.info("Добавлен столбец volume.")

    # --- Фильтрация по периодам ---
    if period and not market_data.empty:
        today = datetime.now()
        if period == "1d":
            start_date = today - timedelta(days=1)
        elif period == "1m":
            start_date = today - timedelta(days=30)
        elif period == "6m":
            start_date = today - timedelta(days=180)
        elif period == "1y":
            start_date = today - timedelta(days=365)
        elif period == "all":
            start_date = None
        else:
            raise ValueError("Неверный параметр period. Используй: 1d, 1m, 6m, 1y, all")

        if start_date:
            market_data = market_data[market_data.index >= start_date]
            logger.info(f"Фильтр по периоду {period}: осталось {len(market_data)} записей.")

    if start:
        market_data = market_data[market_data.index >= pd.to_datetime(start)]
    if end:
        market_data = market_data[market_data.index <= pd.to_datetime(end)]

    logger.info("DataFrame успешно сформирован.")
    return market_data


