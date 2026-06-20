# ============================================================================
#  ELITE TRADING BOT v2.2 - AGGRESSIVE TEST ENGINE (UNLEASHED)
#  Markt: Crypto (Volledig) + Metalen + Forex | Account: Pepperstone
#  Strategie: Agressieve M15/H1 Testmodus (Verlaagde Drempels)
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
        logging.FileHandler('elite_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─── Config (AGRESSIEVE INSTELLINGEN) ────────────────────────────────────────
@dataclass
class Config:
    BALANCE_RISK_MIN:   float = 0.03   # VERHOOGD: Start direct op 3% risico
    BALANCE_RISK_MAX:   float = 0.07   # VERHOOGD: Maximaal 7% risico
    MAX_DAILY_LOSS_PCT: float = 0.15   # VERHOOGD: Meer ademruimte om te testen (15%)
    MAX_OPEN_TRADES:    int   = 6      
    MAX_TRADES_PER_DAY: int   = 50     # VERHOOGD: Geen vroege circuit breaker
    CONSEC_LOSS_LIMIT:  int   = 8      # VERHOOGD: Pas pauze na 8 verliezen

    TRAIL_TRIGGER_R:    float = 0.8    # SNELLER: Trailing start al op 0.8R
    TRAIL_STEP_R:       float = 0.4    
    PARTIAL_CLOSE_R:    float = 1.2    # SNELLER: Winst harken op 1.2R

    MAX_SPREAD:         dict  = field(default_factory=lambda: {
        'crypto': 9999, 'metals': 9999, 'forex': 9999  # UNLOCKED: Spread filter staat UIT
    })

    TF_TREND:  int = mt5.TIMEFRAME_H4
    TF_SETUP:  int = mt5.TIMEFRAME_H1
    TF_ENTRY:  int = mt5.TIMEFRAME_M15
    MAGIC:     int = 999888

CFG = Config()

PAIRS = {
    'crypto': [
        'BTCUSD', 'ETHUSD', 'BNBUSD', 'SOLUSD', 'XRPUSD', 
        'ADAUSD', 'LTCUSD', 'LINKUSD', 'AVAXUSD', 'DOTUSD', 
        'UNIUSD', 'XLMUSD', 'DOGEUSD', 'SHIBUSD'
    ],
    'metals': ['XAUUSD', 'XAGUSD'],
    'forex':  ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD']
}
ALL_PAIRS = [p for group in PAIRS.values() for p in group]

def get_market(symbol):
    for market, symbols in PAIRS.items():
        if symbol in symbols: return market
    return 'forex'

state = {
    'daily_loss':     0.0,
    'daily_trades':   0,
    'consec_losses':  0,
    'start_balance':  0.0,
    'paused':         False,
    'pause_until':    None,
    'partial_closed': set(),   
    'verwerkte_deals': set()  
}

def connect():
    if not mt5.initialize():
        log.error(f"MT5 init mislukt: {mt5.last_error()}")
        return False
    acc = mt5.account_info()
    if not acc: return False
    log.info(f"✅ UNLEASHED MODUS LIVE | Account: {acc.login} | Balance: €{acc.balance:,.2f}")
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
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_mid']

    low14  = df['low'].rolling(14).min()
    high14 = df['high'].rolling(14).max()
    df['stoch_k'] = 100 * (df['close'] - low14) / (high14 - low14 + 1e-9)
    df['stoch_d'] = df['stoch_k'].rolling(3).mean()

    df['vol_sma'] = df['tick_volume'].rolling(20).mean()
    df['vol_ratio'] = df['tick_volume'] / df['vol_sma'].replace(0, 1)
    return df

def analyze(symbol) -> Optional[Signal]:
    h4 = candles(symbol, CFG.TF_TREND, 300)
    h1 = candles(symbol, CFG.TF_SETUP, 200)
    m15 = candles(symbol, CFG.TF_ENTRY, 150)

    if h4 is None or h1 is None or m15 is None: return None

    h4  = add_indicators(h4)
    h1  = add_indicators(h1)
    m15 = add_indicators(m15)

    L4  = h4.iloc[-1];  P4  = h4.iloc[-2]
    L1  = h1.iloc[-1];  P1  = h1.iloc[-2]
    LM  = m15.iloc[-1]; PM  = m15.iloc[-2]

    score_buy  = 0
    score_sell = 0
    reasons    = []

    if L4['close'] > L4['ema200']:
        score_buy += 1
        if L4['ema50'] > L4['ema200']:
            score_buy += 1
            reasons.append("H4 bull trend")
        if L4['ema21'] > L4['ema50']: score_buy += 1
    else:
        score_sell += 1
        if L4['ema50'] < L4['ema200']:
            score_sell += 1
            reasons.append("H4 bear trend")
        if L4['ema21'] < L4['ema50']: score_sell += 1

    if P1['macd_hist'] < 0 and L1['macd_hist'] > 0:
        score_buy += 1
        reasons.append("H1 MACD cross up")
    if P1['macd_hist'] > 0 and L1['macd_hist'] < 0:
        score_sell += 1
        reasons.append("H1 MACD cross down")

    if 45 < L1['rsi'] < 65: score_buy += 1
    if 35 < L1['rsi'] < 55: score_sell += 1

    if L1['ema8'] > L1['ema21'] and P1['ema8'] <= P1['ema21']:
        score_buy += 1
        reasons.append("H1 EMA8 cross")
    if L1['ema8'] < L1['ema21'] and P1['ema8'] >= P1['ema21']:
        score_sell += 1
        reasons.append("H1 EMA8 cross down")

    if PM['stoch_k'] < 25 and LM['stoch_k'] > PM['stoch_k']:
        score_buy += 1
        reasons.append("M15 Stoch oversold bounce")
    if PM['stoch_k'] > 75 and LM['stoch_k'] < PM['stoch_k']:
        score_sell += 1
        reasons.append("M15 Stoch overbought drop")

    if LM['close'] <= LM['bb_lower'] * 1.001:
        score_buy += 1
        reasons.append("M15 BB lower touch")
    if LM['close'] >= LM['bb_upper'] * 0.999:
        score_sell += 1
        reasons.append("M15 BB upper touch")

    if LM['vol_ratio'] > 1.2: # GEVOELIGER: Volume drempel verlaagd van 1.5 naar 1.2
        if LM['close'] > LM['open']:
            score_buy += 1
            reasons.append("Volume spike bull")
        else:
            score_sell += 1
            reasons.append("Volume spike bear")

    candle_size = abs(LM['close'] - LM['open'])
    if candle_size > LM['atr'] * 0.4: # GEVOELIGER: Candle size filter verlaagd
        if LM['close'] > LM['open']: score_buy += 1
        else: score_sell += 1

    atr = LM['atr']

    # TEST TRIGGER: Drempel verlaagd van 6 naar 4 punten confluency!
    if score_buy >= 4 and score_buy > score_sell:
        return Signal(symbol=symbol, direction='BUY', score=min(score_buy, 10), atr=atr, reason=' | '.join(reasons))
    elif score_sell >= 4 and score_sell > score_buy:
        return Signal(symbol=symbol, direction='SELL', score=min(score_sell, 10), atr=atr, reason=' | '.join(reasons))

    return None

def calc_lot(symbol, atr, score) -> float:
    acc = account()
    if not acc: return 0.01
    balance = acc.balance

    risk_pct = CFG.BALANCE_RISK_MIN + ((score - 4) / 6 * (CFG.BALANCE_RISK_MAX - CFG.BALANCE_RISK_MIN))
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
    direction = signal.direction

    t = tick(sym)
    i = info(sym)
    if not t or not i: return False

    lot = calc_lot(sym, atr, signal.score)
    sl_dist = atr * 1.5
    tp_dist = atr * 3.0   

    if direction == 'BUY':
        price, otype = t.ask, mt5.ORDER_TYPE_BUY
        sl, tp = price - sl_dist, price + tp_dist
    else:
        price, otype = t.bid, mt5.ORDER_TYPE_SELL
        sl, tp = price + sl_dist, price - tp_dist

    req = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       sym,
        "volume":       lot,
        "type":         otype,
        "price":        price,
        "sl":           round(sl, i.digits),
        "tp":           round(tp, i.digits),
        "magic":        CFG.MAGIC,
        "comment":      f"Test|{signal.score}",
        "type_time":    mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(req)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"🔥 AGGRESSIVE TRIGGER {direction} {sym} | lot={lot} | score={signal.score}/10")
        state['daily_trades'] += 1
        return True
    else:
        log.error(f"❌ Order mislukt {sym}: {result.retcode}")
        return False

def manage_positions():
    for pos in positions():
        sym = pos.symbol
        i, t = info(sym), tick(sym)
        if not i or not t: continue

        is_buy   = pos.type == mt5.ORDER_TYPE_BUY
        entry    = pos.price_open
        current  = t.bid if is_buy else t.ask
        sl, tp, ticket = pos.sl, pos.tp, pos.ticket

        if sl == 0 or tp == 0: continue
        risk_dist = abs(entry - sl)
        if risk_dist == 0: continue

        profit_dist = (current - entry) if is_buy else (entry - current)
        profit_r    = profit_dist / risk_dist   

        if profit_r >= CFG.PARTIAL_CLOSE_R and ticket not in state['partial_closed']:
            close_volume = round(pos.volume * 0.5, 2)
            close_volume = max(i.volume_min, close_volume)
            if close_volume < pos.volume:
                req = {
                    "action":   mt5.TRADE_ACTION_DEAL, "symbol": sym, "volume": close_volume,
                    "type":     mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                    "position": ticket, "price": t.bid if is_buy else t.ask,
                    "magic":    CFG.MAGIC, "comment": "Test|Partial",
                    "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
                }
                if mt5.order_send(req).retcode == mt5.TRADE_RETCODE_DONE:
                    state['partial_closed'].add(ticket)
                    log.info(f"📊 Partieel gesloten {sym} {close_volume} lot @ {profit_r:.1f}R")

        if profit_r >= CFG.TRAIL_TRIGGER_R:
            trail_offset = risk_dist * CFG.TRAIL_STEP_R
            if is_buy:
                new_sl = round(current - trail_offset, i.digits)
                if new_sl > sl + i.point: _modify_sl(pos, new_sl)
            else:
                new_sl = round(current + trail_offset, i.digits)
                if new_sl < sl - i.point: _modify_sl(pos, new_sl)

def _modify_sl(pos, new_sl):
    req = {"action": mt5.TRADE_ACTION_SLTP, "position": pos.ticket, "symbol": pos.symbol, "sl": new_sl, "tp": pos.tp, "magic": CFG.MAGIC}
    if mt5.order_send(req).retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"🔒 Trailing SL {pos.symbol} → {new_sl:.5f}")

def check_risk() -> bool:
    acc = account()
    if not acc: return False

    daily_loss_pct = (state['start_balance'] - acc.equity) / state['start_balance']
    if daily_loss_pct >= CFG.MAX_DAILY_LOSS_PCT:
        log.warning(f"🛑 Dagelijks verlies limiet bereikt: {daily_loss_pct*100:.1f}%")
        return False

    if state['daily_trades'] >= CFG.MAX_TRADES_PER_DAY:
        log.warning(f"🛑 Max trades per dag bereikt: {state['daily_trades']}")
        return False

    if state['consec_losses'] >= CFG.CONSEC_LOSS_LIMIT:
        if state['pause_until'] is None:
            state['pause_until'] = datetime.now() + timedelta(minutes=30)
            log.warning(f"⏸ {CFG.CONSEC_LOSS_LIMIT} verliezen — pauze 30 min")
        if datetime.now() < state['pause_until']: return False
        else:
            state['consec_losses'] = 0
            state['pause_until']   = None
            log.info("▶️ Pauze voorbij — bot hervat")

    if len(positions()) >= CFG.MAX_OPEN_TRADES: return False
    return True

def track_closed_trades():
    deals = mt5.history_deals_get(datetime.now() - timedelta(hours=24), datetime.now())
    if not deals: return

    my_deals = [d for d in deals if d.magic == CFG.MAGIC and d.entry == mt5.DEAL_ENTRY_OUT]
    if not my_deals: return

    last = my_deals[-1]
    if last.ticket not in state['verwerkte_deals']:
        state['verwerkte_deals'].add(last.ticket)
        if last.profit < 0:
            state['consec_losses'] += 1
            log.info(f"📉 Deal {last.ticket} verloren. Streak: {state['consec_losses']}")
        else:
            state['consec_losses'] = 0
            log.info(f"📈 Deal {last.ticket} gewonnen. Streak gereset naar 0.")

last_reset = datetime.now().date()

def daily_reset():
    global last_reset
    today = datetime.now().date()
    if today != last_reset:
        acc = account()
        if acc:
            state['start_balance'] = acc.balance
            state['daily_trades']  = 0
            state['consec_losses'] = 0
            state['pause_until']   = None
            state['partial_closed'].clear()
            state['verwerkte_deals'].clear()
            last_reset = today
            log.info(f"🌅 Nieuwe handelsdag | Balance: €{acc.balance:,.2f}")

def main():
    if not connect(): return
    cycle = 0

    while True:
        try:
            cycle += 1
            daily_reset()
            track_closed_trades()
            manage_positions()

            if check_risk():
                log.info(f"🔍 [TEST SPREAD-FREE] Scan #{cycle} | Open: {len(positions())}/{CFG.MAX_OPEN_TRADES}")
                for symbol in ALL_PAIRS:
                    if positions(symbol): continue
                    signal = analyze(symbol)
                    if signal:
                        open_trade(signal)
                        time.sleep(1)
            time.sleep(10) # SUPERSNEL: Scan interval verlaagd naar 10 seconden voor directe actie!

        except KeyboardInterrupt: break
        except Exception as e:
            log.error(f"Fout: {e}", exc_info=True)
            time.sleep(10)
    mt5.shutdown()

if __name__ == "__main__":
    main()