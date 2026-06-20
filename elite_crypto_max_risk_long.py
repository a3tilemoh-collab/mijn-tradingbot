# ============================================================================
#  ELITE TRADING BOT v3.0 - UNLEASHED CRYPTO-ONLY MAX RISK ENGINE
#  Markt: Uitsluitend Crypto Matrix (14 Assets) | Account: Pepperstone
#  Strategie: Hyper-Agressieve Long-Only Trigger (No Limits)
# ============================================================================

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

# ─── Logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('crypto_max_risk.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─── Hyper-Agressieve Instellingen (MAX RISK) ───────────────────────────────
@dataclass
class Config:
    BALANCE_RISK_MIN:   float = 0.10   # CRITICAL RISK: Start direct op 10% risico per trade!
    BALANCE_RISK_MAX:   float = 0.15   # MAXIMUM RISK: Tot 15% risico bij confluency!
    MAX_DAILY_LOSS_PCT: float = 0.90   # UNLOCKED: Bot stopt pas na 90% verlies
    MAX_OPEN_TRADES:    int   = 6      # Max posities tegelijk open
    MAX_TRADES_PER_DAY: int   = 200    # Geen daglimiet filters
    CONSEC_LOSS_LIMIT:  int   = 99     # Geen verplichte pauzes

    TRAIL_TRIGGER_R:    float = 0.5    # ULTRA SNEL: Trailing start al direct op 0.5R
    TRAIL_STEP_R:       float = 0.25   
    PARTIAL_CLOSE_R:    float = 1.0    # Pak 50% winst direct op 1:1 risk/reward

    # Spread filter volledig gedeactiveerd
    MAX_SPREAD: int = 99999
    
    TF_TREND:  int = mt5.TIMEFRAME_H4
    TF_SETUP:  int = mt5.TIMEFRAME_H1
    TF_ENTRY:  int = mt5.TIMEFRAME_M15
    MAGIC:     int = 777111  # Exclusief Magic Number voor deze Max Risk Crypto run

CFG = Config()

# Uitsluitend de complete cryptomarkt ingeladen
CRYPTO_PAIRS = [
    'BTCUSD', 'ETHUSD', 'BNBUSD', 'SOLUSD', 'XRPUSD', 
    'ADAUSD', 'LTCUSD', 'LINKUSD', 'AVAXUSD', 'DOTUSD', 
    'UNIUSD', 'XLMUSD', 'DOGEUSD', 'SHIBUSD'
]

state = {
    'start_balance':  0.0,
    'verwerkte_deals': set()
}

@dataclass
class Signal:
    symbol:    str
    direction: str        
    score:     int        
    atr:       float
    reason:    str

# ─── MT5 Helpers ────────────────────────────────────────────────────────────
def connect():
    if not mt5.initialize():
        log.error(f"MT5 init mislukt: {mt5.last_error()}")
        return False
    acc = mt5.account_info()
    if not acc: return False
    log.info(f"🔥 CRYPTO MAX RISK LONG ENGINE ONLINE | Account: {acc.login} | Balance: €{acc.balance:,.2f}")
    state['start_balance'] = acc.balance
    return True

def candles(symbol, tf, count=300):
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) < 50: return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def tick(symbol): return mt5.symbol_info_tick(symbol)
def info(symbol): return mt5.symbol_info(symbol)
def account(): return mt5.account_info()

def positions(symbol=None):
    if symbol:
        pos = mt5.positions_get(symbol=symbol, magic=CFG.MAGIC)
    else:
        pos = mt5.positions_get(magic=CFG.MAGIC)
    return list(pos) if pos is not None else []

def add_indicators(df):
    df['ema8']   = df['close'].ewm(span=8, adjust=False).mean()
    df['ema21']  = df['close'].ewm(span=21, adjust=False).mean()
    df['ema50']  = df['close'].ewm(span=50, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    delta = df['close'].diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = (-delta.clip(upper=0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd']        = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist']   = df['macd'] - df['macd_signal']

    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low']  - df['close'].shift()).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()

    df['bb_mid']   = df['close'].rolling(20).mean()
    bb_std        = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_mid'] + 2 * bb_std
    df['bb_lower'] = df['bb_mid'] - 2 * bb_std

    low14  = df['low'].rolling(14).min()
    high14 = df['high'].rolling(14).max()
    df['stoch_k'] = 100 * (df['close'] - low14) / (high14 - low14 + 1e-9)
    return df

def analyze(symbol) -> Optional[Signal]:
    h4 = candles(symbol, CFG.TF_TREND, 200)
    h1 = candles(symbol, CFG.TF_SETUP, 150)
    m15 = candles(symbol, CFG.TF_ENTRY, 100)

    if h4 is None or h1 is None or m15 is None: return None

    h4  = add_indicators(h4)
    h1  = add_indicators(h1)
    m15 = add_indicators(m15)

    L4  = h4.iloc[-1]
    L1  = h1.iloc[-1];  P1  = h1.iloc[-2]
    LM  = m15.iloc[-1]; PM  = m15.iloc[-2]

    score_buy = 0

    # Hyper-Gevoelige Logica (Vanaf 3 punten direct schieten)
    if L4['close'] > L4['ema50']: score_buy += 1
    if L1['macd_hist'] > 0: score_buy += 1
    if L1['ema8'] > L1['ema21']: score_buy += 1
    if LM['stoch_k'] > PM['stoch_k']: score_buy += 1
    if LM['close'] > LM['open']: score_buy += 1

    atr = LM['atr']

    if score_buy >= 3:
        return Signal(symbol=symbol, direction='BUY', score=score_buy, atr=atr, reason='Max Risk Trigger')

    return None

def calc_lot(symbol, atr, score) -> float:
    acc = account()
    if not acc: return 0.01
    balance = acc.balance

    # Schaal op naar gigantische lots
    risk_pct = CFG.BALANCE_RISK_MIN + ((score - 3) / 5 * (CFG.BALANCE_RISK_MAX - CFG.BALANCE_RISK_MIN))
    risk_pct = max(CFG.BALANCE_RISK_MIN, min(CFG.BALANCE_RISK_MAX, risk_pct))
    risk_amount = balance * risk_pct

    sl_distance = atr * 1.5
    sym_info = info(symbol)
    if not sym_info: return 0.01

    point       = sym_info.point
    tick_size   = sym_info.trade_tick_size
    tick_value  = sym_info.trade_tick_value
    lot_step    = sym_info.volume_step
    lot_min     = sym_info.volume_min
    lot_max     = sym_info.volume_max

    if tick_size > 0 and tick_value > 0:
        pip_value = tick_value / tick_size * point
    else:
        pip_value = 10.0  

    if pip_value <= 0 or sl_distance <= 0: return lot_min

    lot = risk_amount / (sl_distance / point * pip_value)
    lot = round(lot / lot_step) * lot_step
    lot = max(lot_min, min(lot_max, lot))
    return round(lot, 2)

def open_trade(signal: Signal) -> bool:
    sym = signal.symbol
    atr = signal.atr

    t = tick(sym)
    i = info(sym)
    if not t or not i: return False

    lot = calc_lot(sym, atr, signal.score)
    sl_dist = atr * 1.2  # Iets strakkere SL voor groter volume
    tp_dist = atr * 3.0   

    price = t.ask
    sl = price - sl_dist
    tp = price + tp_dist

    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       sym,
        "volume":       lot,
        "type":         mt5.ORDER_TYPE_BUY,
        "price":        price,
        "sl":           round(sl, i.digits),
        "tp":           round(tp, i.digits),
        "magic":        CFG.MAGIC,
        "comment":      f"MaxRisk|{signal.score}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(req)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"💥 GIGANTIC LONG ORDER DEPLOYED: {sym} | lot={lot} | score={signal.score}/5")
        return True
    else:
        log.error(f"❌ Order geweigerd {sym}: {result.retcode}")
        return False

def manage_positions():
    for pos in positions():
        sym = pos.symbol
        i, t = info(sym), tick(sym)
        if not i or not t: continue

        entry    = pos.price_open
        current  = t.bid
        sl, ticket = pos.sl, pos.ticket

        if sl == 0: continue
        risk_dist = abs(entry - sl)
        if risk_dist == 0: continue

        profit_dist = current - entry
        profit_r    = profit_dist / risk_dist   

        # Aggressieve trailing stop update
        if profit_r >= CFG.TRAIL_TRIGGER_R:
            trail_offset = risk_dist * CFG.TRAIL_STEP_R
            new_sl = round(current - trail_offset, i.digits)
            if new_sl > sl + i.point:
                req = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "symbol": sym, "sl": new_sl, "tp": pos.tp, "magic": CFG.MAGIC}
                mt5.order_send(req)
                log.info(f"🔒 Trail SL aangespannen voor {sym} → {new_sl:.5f}")

def main():
    if not connect(): return
    cycle = 0

    while True:
        try:
            cycle += 1
            manage_positions()

            acc = account()
            if acc and ((state['start_balance'] - acc.equity) / state['start_balance'] < CFG.MAX_DAILY_LOSS_PCT):
                log.info(f"🔍 [CRYPTO HUNT] Scan #{cycle} | Live open: {len(positions())}/{CFG.MAX_OPEN_TRADES}")
                
                for symbol in CRYPTO_PAIRS:
                    if len(positions()) >= CFG.MAX_OPEN_TRADES: break
                    if positions(symbol): continue
                    
                    signal = analyze(symbol)
                    if signal:
                        open_trade(signal)
                        time.sleep(1)
            
            time.sleep(10)  # Onbarmhartige 10-seconden loop

        except KeyboardInterrupt: break
        except Exception as e:
            time.sleep(10)
    mt5.shutdown()

if __name__ == "__main__":
    main()