# Trading Bot Server - Flask backend voor MT5
# Verbindt met MetaTrader 5 en exposed een REST API voor de PWA
# Start met: python trading_bot_server.py

from flask import Flask, jsonify, request
from flask_cors import CORS
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import threading
import time
import json
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Staat verbinding toe van je telefoon

# ─── Bot State ───────────────────────────────────────────────────────────────
bot_state = {
    "running": False,
    "strategy": None,       # "ema", "rsi", "scalper"
    "symbol": None,
    "lot_size": 0.01,
    "magic": 234567,
    "logs": [],
    "stats": {
        "total_trades": 0,
        "wins": 0,
        "losses": 0,
        "profit": 0.0,
        "open_trades": 0
    }
}

bot_thread = None

SUPPORTED_SYMBOLS = [
    "BTCUSD", "ETHUSD", "XAUUSD", "EURUSD",
    "GBPUSD", "USDJPY", "XRPUSD", "LTCUSD"
]

# ─── Logging ──────────────────────────────────────────────────────────────────
def log(msg, level="INFO"):
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "msg": msg
    }
    bot_state["logs"].insert(0, entry)
    if len(bot_state["logs"]) > 100:
        bot_state["logs"] = bot_state["logs"][:100]
    print(f"[{entry['time']}] [{level}] {msg}")

# ─── MT5 Helpers ─────────────────────────────────────────────────────────────
def mt5_connect():
    if not mt5.initialize():
        log(f"MT5 init failed: {mt5.last_error()}", "ERROR")
        return False
    log("MT5 verbonden", "OK")
    return True

def get_candles(symbol, timeframe=mt5.TIMEFRAME_M5, count=200):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def get_open_trade(symbol):
    positions = mt5.positions_get(symbol=symbol)
    if positions:
        return positions[0]
    return None

def open_trade(symbol, direction, lot, sl_pips=50, tp_pips=100):
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if not tick or not info:
        log(f"Kan tick/info niet ophalen voor {symbol}", "ERROR")
        return False

    point = info.point
    if direction == "BUY":
        price = tick.ask
        sl = price - sl_pips * point
        tp = price + tp_pips * point
        trade_type = mt5.ORDER_TYPE_BUY
    else:
        price = tick.bid
        sl = price + sl_pips * point
        tp = price - tp_pips * point
        trade_type = mt5.ORDER_TYPE_SELL

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": trade_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "magic": bot_state["magic"],
        "comment": f"Bot-{bot_state['strategy']}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        log(f"✅ {direction} {symbol} @ {price:.5f} | lot={lot}", "TRADE")
        bot_state["stats"]["total_trades"] += 1
        bot_state["stats"]["open_trades"] += 1
        return True
    else:
        log(f"Order mislukt: {result.retcode} - {result.comment}", "ERROR")
        return False

def close_trade(position):
    tick = mt5.symbol_info_tick(position.symbol)
    if not tick:
        return False
    if position.type == mt5.ORDER_TYPE_BUY:
        price = tick.bid
        trade_type = mt5.ORDER_TYPE_SELL
    else:
        price = tick.ask
        trade_type = mt5.ORDER_TYPE_BUY

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": trade_type,
        "position": position.ticket,
        "price": price,
        "magic": bot_state["magic"],
        "comment": "Bot-close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        profit = position.profit
        log(f"🔒 Gesloten {position.symbol} | P&L: {profit:.2f}", "TRADE")
        bot_state["stats"]["open_trades"] = max(0, bot_state["stats"]["open_trades"] - 1)
        bot_state["stats"]["profit"] += profit
        if profit >= 0:
            bot_state["stats"]["wins"] += 1
        else:
            bot_state["stats"]["losses"] += 1
        return True
    return False

# ─── Strategieën ─────────────────────────────────────────────────────────────
def strategy_ema(symbol, lot):
    """EMA 20/50 crossover met RSI filter"""
    df = get_candles(symbol, mt5.TIMEFRAME_M15, 200)
    if df is None or len(df) < 60:
        return

    df['ema20'] = df['close'].ewm(span=20).mean()
    df['ema50'] = df['close'].ewm(span=50).mean()
    df['ema200'] = df['close'].ewm(span=200).mean()

    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    last = df.iloc[-1]
    prev = df.iloc[-2]
    rsi = last['rsi']
    trend_up = last['close'] > last['ema200']

    position = get_open_trade(symbol)

    if position is None:
        # BUY: EMA20 kruist omhoog door EMA50, RSI tussen 40-65, prijs boven EMA200
        if (prev['ema20'] < prev['ema50'] and last['ema20'] > last['ema50']
                and 40 < rsi < 65 and trend_up):
            log(f"📈 EMA BUY signaal {symbol} | RSI={rsi:.1f}")
            open_trade(symbol, "BUY", lot)

        # SELL: EMA20 kruist omlaag door EMA50, RSI tussen 35-60, prijs onder EMA200
        elif (prev['ema20'] > prev['ema50'] and last['ema20'] < last['ema50']
              and 35 < rsi < 60 and not trend_up):
            log(f"📉 EMA SELL signaal {symbol} | RSI={rsi:.1f}")
            open_trade(symbol, "SELL", lot)
    else:
        # Exit als RSI overbought/oversold
        if position.type == mt5.ORDER_TYPE_BUY and rsi > 75:
            log(f"⚠️ RSI overbought {rsi:.1f}, sluit BUY")
            close_trade(position)
        elif position.type == mt5.ORDER_TYPE_SELL and rsi < 25:
            log(f"⚠️ RSI oversold {rsi:.1f}, sluit SELL")
            close_trade(position)


def strategy_rsi_dip(symbol, lot):
    """RSI Dip-buyer: koop oververkochte dips in uptrend"""
    df = get_candles(symbol, mt5.TIMEFRAME_M15, 100)
    if df is None or len(df) < 20:
        return

    delta = df['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    df['ema50'] = df['close'].ewm(span=50).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]
    rsi = last['rsi']
    prev_rsi = prev['rsi']

    position = get_open_trade(symbol)

    if position is None:
        # BUY dip: RSI was onder 30, stijgt nu terug (bounce)
        if prev_rsi < 30 and rsi > prev_rsi and last['close'] > last['ema50']:
            log(f"🎯 RSI dip bounce {symbol} | RSI={rsi:.1f}")
            open_trade(symbol, "BUY", lot, sl_pips=40, tp_pips=80)

        # SELL dip: RSI was boven 70, daalt nu (overbought sell)
        elif prev_rsi > 70 and rsi < prev_rsi and last['close'] < last['ema50']:
            log(f"🎯 RSI overbought sell {symbol} | RSI={rsi:.1f}")
            open_trade(symbol, "SELL", lot, sl_pips=40, tp_pips=80)
    else:
        # Exit bij RSI middengebied
        if position.type == mt5.ORDER_TYPE_BUY and rsi > 60:
            log(f"🔒 RSI target bereikt {rsi:.1f}, sluit BUY")
            close_trade(position)
        elif position.type == mt5.ORDER_TYPE_SELL and rsi < 40:
            log(f"🔒 RSI target bereikt {rsi:.1f}, sluit SELL")
            close_trade(position)


def strategy_scalper(symbol, lot):
    """Scalper: snelle M1 trades op momentum"""
    df = get_candles(symbol, mt5.TIMEFRAME_M1, 50)
    if df is None or len(df) < 20:
        return

    df['ema5'] = df['close'].ewm(span=5).mean()
    df['ema10'] = df['close'].ewm(span=10).mean()

    # ATR voor volatiliteit check
    df['tr'] = np.maximum(
        df['high'] - df['low'],
        np.maximum(
            abs(df['high'] - df['close'].shift()),
            abs(df['low'] - df['close'].shift())
        )
    )
    df['atr'] = df['tr'].rolling(14).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]
    atr = last['atr']

    # Spread check (geen trade bij hoge spread)
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick and info:
        spread = (tick.ask - tick.bid) / info.point
        if spread > 30:
            log(f"⏸️ Spread te hoog: {spread:.0f} pips", "WARN")
            return

    position = get_open_trade(symbol)

    if position is None:
        # BUY momentum: EMA5 kruist EMA10 omhoog
        if prev['ema5'] < prev['ema10'] and last['ema5'] > last['ema10']:
            log(f"⚡ Scalp BUY {symbol}")
            open_trade(symbol, "BUY", lot, sl_pips=15, tp_pips=25)

        # SELL momentum: EMA5 kruist EMA10 omlaag
        elif prev['ema5'] > prev['ema10'] and last['ema5'] < last['ema10']:
            log(f"⚡ Scalp SELL {symbol}")
            open_trade(symbol, "SELL", lot, sl_pips=15, tp_pips=25)
    else:
        # Tijd-gebaseerde exit voor scalper (max 30 min open)
        open_time = pd.Timestamp(position.time, unit='s')
        now = pd.Timestamp.now()
        minutes_open = (now - open_time).seconds / 60
        if minutes_open > 30:
            log(f"⏱️ Scalp timeout {minutes_open:.0f}min, sluit positie")
            close_trade(position)


# ─── Bot Loop ─────────────────────────────────────────────────────────────────
def bot_loop():
    log("🤖 Bot gestart", "OK")
    if not mt5_connect():
        bot_state["running"] = False
        return

    strategy_map = {
        "ema": strategy_ema,
        "rsi": strategy_rsi_dip,
        "scalper": strategy_scalper
    }

    sleep_map = {
        "ema": 60,
        "rsi": 60,
        "scalper": 15
    }

    while bot_state["running"]:
        strategy = bot_state["strategy"]
        symbol = bot_state["symbol"]
        lot = bot_state["lot_size"]

        if strategy and symbol:
            try:
                fn = strategy_map.get(strategy)
                if fn:
                    fn(symbol, lot)
            except Exception as e:
                log(f"Fout in strategie: {e}", "ERROR")

        sleep_time = sleep_map.get(strategy, 30)
        for _ in range(sleep_time):
            if not bot_state["running"]:
                break
            time.sleep(1)

    mt5.shutdown()
    log("🛑 Bot gestopt", "WARN")


# ─── API Endpoints ────────────────────────────────────────────────────────────
@app.route("/api/status")
def status():
    positions = []
    if mt5.initialize():
        pos = mt5.positions_get()
        if pos:
            for p in pos:
                positions.append({
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "type": "BUY" if p.type == 0 else "SELL",
                    "volume": p.volume,
                    "open_price": p.price_open,
                    "profit": round(p.profit, 2),
                    "time": datetime.fromtimestamp(p.time).strftime("%H:%M:%S")
                })
        account = mt5.account_info()
        balance = round(account.balance, 2) if account else 0
        equity = round(account.equity, 2) if account else 0
        mt5.shutdown()
    else:
        balance = 0
        equity = 0

    return jsonify({
        "running": bot_state["running"],
        "strategy": bot_state["strategy"],
        "symbol": bot_state["symbol"],
        "lot_size": bot_state["lot_size"],
        "stats": bot_state["stats"],
        "logs": bot_state["logs"][:20],
        "positions": positions,
        "balance": balance,
        "equity": equity
    })

@app.route("/api/start", methods=["POST"])
def start():
    global bot_thread
    data = request.json
    if bot_state["running"]:
        return jsonify({"ok": False, "msg": "Bot draait al"})

    bot_state["strategy"] = data.get("strategy", "ema")
    bot_state["symbol"] = data.get("symbol", "BTCUSD")
    bot_state["lot_size"] = float(data.get("lot_size", 0.01))
    bot_state["running"] = True

    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()

    log(f"▶️ Start: {bot_state['strategy'].upper()} op {bot_state['symbol']}", "OK")
    return jsonify({"ok": True, "msg": f"Bot gestart: {bot_state['strategy']} | {bot_state['symbol']}"})

@app.route("/api/stop", methods=["POST"])
def stop():
    bot_state["running"] = False
    log("⏹️ Stop aangevraagd door gebruiker", "WARN")
    return jsonify({"ok": True, "msg": "Bot wordt gestopt..."})

@app.route("/api/symbols")
def symbols():
    return jsonify({"symbols": SUPPORTED_SYMBOLS})

@app.route("/api/reset_stats", methods=["POST"])
def reset_stats():
    bot_state["stats"] = {
        "total_trades": 0, "wins": 0,
        "losses": 0, "profit": 0.0, "open_trades": 0
    }
    return jsonify({"ok": True})

if __name__ == "__main__":
    print("=" * 50)
    print("  Trading Bot Server")
    print("  http://0.0.0.0:5000")
    print("  Zorg dat MT5 open is met AutoTrading AAN")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
