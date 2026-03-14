import logging
from io import BytesIO
import matplotlib.pyplot as plt
import pandas as pd


# --- Логирование ---
logger = logging.getLogger(__name__)


def plot_with_levels(df: pd.DataFrame, analysis: dict, ticker: str):
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
