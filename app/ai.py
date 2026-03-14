import os
import logging
import json
from openai import OpenAI
from dotenv import load_dotenv
from pandas import DataFrame
import pandas as pd


# --- Логирование ---
logger = logging.getLogger(__name__)

# --- Загружаем переменные окружения ---
load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


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
