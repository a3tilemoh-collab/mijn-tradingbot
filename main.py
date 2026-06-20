# ============================================================
#  UniversalBot - main.py
#  Hoofdloop: forex, crypto en metalen op MT5
# ============================================================
#  Start met: python main.py
#  Stop met:  Ctrl+C
# ============================================================

import time
import logging
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd

from config import SYMBOLS, RISK, MT5 as MT5_CFG
from strategy_engine import calculate_indicators, get_signal
from risk_manager import calc_lot_size, check_spread, check_daily_loss, get_account_summary
from execution_layer import place_order, already_has_position

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("universalbot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

SCAN_INTERVAL = 300   # seconden tussen elke scan (5 min)
TIMEFRAME     = mt5.TIMEFRAME_H1
BARS          = 300


# ─────────────────────────────────────────────────────────────────────────────
#  DATA OPHALEN
# ─────────────────────────────────────────────────────────────────────────────

def get_data(symbol: str) -> pd.DataFrame:
    rates = mt5.copy_rates_from_pos(symbol, TIMEFRAME, 0, BARS)
    if rates is None or len(rates) == 0:
        raise ValueError(f"Geen data voor {symbol}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.rename(columns={"tick_volume": "volume"}, inplace=True)
    return df[["time", "open", "high", "low", "close", "volume"]].copy()


# ─────────────────────────────────────────────────────────────────────────────
#  SCAN ÉÉN SYMBOL
# ─────────────────────────────────────────────────────────────────────────────

def scan_symbol(symbol: str):
    # Al open positie? Overslaan.
    if already_has_position(symbol):
        return

    # Spread check
    if not check_spread(symbol):
        logger.debug(f"  {symbol}: spread te groot, overgeslagen")
        return

    # Data + indicatoren
    df     = get_data(symbol)
    df     = calculate_indicators(df)
    signal, atr = get_signal(df)

    if signal is None:
        return

    last_price = df["close"].iloc[-1]
    sl_dist    = atr * RISK["atr_sl_multiplier"]
    tp_dist    = atr * RISK["atr_tp_multiplier"]

    if signal == "BUY":
        sl = last_price - sl_dist
        tp = last_price + tp_dist
    else:
        sl = last_price + sl_dist
        tp = last_price - tp_dist

    lot = calc_lot_size(symbol, sl_dist)

    logger.info(f"📶 Signaal: {signal} {symbol} | ATR={atr:.5f} | lot={lot:.2f} | SL={sl:.5f} | TP={tp:.5f}")
    place_order(symbol, signal, lot, sl, tp)


# ─────────────────────────────────────────────────────────────────────────────
#  HOOFDLOOP
# ─────────────────────────────────────────────────────────────────────────────

def main():
    logger.info("═" * 55)
    logger.info("  🤖  UniversalBot gestart")
    logger.info("═" * 55)

    # MT5 verbinden
    if not mt5.initialize():
        logger.error(f"MT5 initialisatie mislukt: {mt5.last_error()}")
        logger.error("Zorg dat MT5 open is en 'Algo Trading' is ingeschakeld.")
        return

    acc = get_account_summary()
    logger.info(f"  Account: balance=${acc.get('balance', 0):,.2f} | equity=${acc.get('equity', 0):,.2f}")
    logger.info(f"  Server : {mt5.account_info().server}")
    logger.info("")

    all_symbols = SYMBOLS["forex"] + SYMBOLS["crypto"] + SYMBOLS["metals"]

    try:
        while True:
            logger.info(f"── Scan gestart: {datetime.now().strftime('%H:%M:%S')} ──────────────────")

            # Dagverlies check
            if not check_daily_loss():
                logger.warning("⛔  Daglimiet bereikt! Bot pauzeert tot morgen.")
                time.sleep(3600)
                continue

            for symbol in all_symbols:
                try:
                    scan_symbol(symbol)
                except Exception as e:
                    logger.warning(f"  ⚠️  {symbol}: {e}")

            acc = get_account_summary()
            logger.info(f"  Balance: ${acc.get('balance', 0):,.2f} | P&L vandaag: ${acc.get('pl_today', 0):+,.2f} ({acc.get('pl_pct', 0):+.2f}%)")
            logger.info(f"  Volgende scan over {SCAN_INTERVAL // 60} minuten...\n")

            time.sleep(SCAN_INTERVAL)

    except KeyboardInterrupt:
        logger.info("\n  🛑  Bot gestopt door gebruiker.")

    finally:
        mt5.shutdown()
        logger.info("  MT5 verbinding gesloten.")


if __name__ == "__main__":
    main()
