# ============================================================
#  UniversalBot - strategy_engine.py
#  EMA crossover + RSI filter + ATR-gebaseerde stops
# ============================================================

import pandas as pd
import numpy as np
from config import STRATEGY


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Berekent alle technische indicatoren op de OHLCV dataframe.
    Verwacht kolommen: open, high, low, close, volume
    """
    s = STRATEGY

    # EMA's
    df["ema_fast"]  = df["close"].ewm(span=s["ema_fast"],  adjust=False).mean()
    df["ema_slow"]  = df["close"].ewm(span=s["ema_slow"],  adjust=False).mean()
    df["ema_trend"] = df["close"].ewm(span=s["ema_trend"], adjust=False).mean()

    # RSI
    delta = df["close"].diff()
    gain  = delta.clip(lower=0).rolling(s["rsi_period"]).mean()
    loss  = (-delta.clip(upper=0)).rolling(s["rsi_period"]).mean()
    rs    = gain / (loss + 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))

    # ATR (True Range)
    hl  = df["high"] - df["low"]
    hc  = (df["high"] - df["close"].shift(1)).abs()
    lc  = (df["low"]  - df["close"].shift(1)).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr"] = tr.rolling(s["atr_period"]).mean()

    # EMA crossover flags
    df["cross_up"] = (df["ema_fast"] > df["ema_slow"]) & (df["ema_fast"].shift(1) <= df["ema_slow"].shift(1))
    df["cross_dn"] = (df["ema_fast"] < df["ema_slow"]) & (df["ema_fast"].shift(1) >= df["ema_slow"].shift(1))

    return df


def get_signal(df: pd.DataFrame):
    """
    Geeft 'BUY', 'SELL' of None terug op basis van de laatste bar.
    Returns: (signal: str|None, atr: float)
    """
    s    = STRATEGY
    last = df.iloc[-1]

    atr = last["atr"]
    if pd.isna(atr) or atr == 0:
        return None, 0

    # BUY: EMA crossover omhoog, prijs boven EMA200, RSI niet overkocht
    if last["cross_up"] and last["close"] > last["ema_trend"] and last["rsi"] < s["rsi_sell"]:
        return "BUY", atr

    # SELL: EMA crossover omlaag, prijs onder EMA200, RSI niet oversold
    if last["cross_dn"] and last["close"] < last["ema_trend"] and last["rsi"] > s["rsi_buy"]:
        return "SELL", atr

    return None, atr


def get_all_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Berekent signalen voor ALLE bars — gebruikt door de backtester.
    Voegt een 'signal' kolom toe: 'BUY', 'SELL' of None.
    """
    s = STRATEGY
    df = calculate_indicators(df)

    conditions_buy  = df["cross_up"] & (df["close"] > df["ema_trend"]) & (df["rsi"] < s["rsi_sell"])
    conditions_sell = df["cross_dn"] & (df["close"] < df["ema_trend"]) & (df["rsi"] > s["rsi_buy"])

    df["signal"] = None
    df.loc[conditions_buy,  "signal"] = "BUY"
    df.loc[conditions_sell, "signal"] = "SELL"

    return df
