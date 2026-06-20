import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
from datetime import datetime

# ====================================================================
# INSTITUTIONAL SNIPER ENGINE (v9.0 - QUANT FINE-TUNED EDITION)
# ====================================================================
MARKET_CONFIG = {
    "BTCUSD":   {"volume": 0.20, "trailing_pips": 200.0, "min_profit": 50.0}, 
    "ETHUSD":   {"volume": 0.20, "trailing_pips": 120.0, "min_profit": 30.0}, 
    "EURUSD":   {"volume": 0.50, "trailing_pips": 0.0040, "min_profit": 0.0015}, # 15 pips winst = trigger
    "GBPUSD":   {"volume": 0.50, "trailing_pips": 0.0040, "min_profit": 0.0015},
    "USDJPY":   {"volume": 0.50, "trailing_pips": 0.400,  "min_profit": 0.150},
    "XAUUSD":   {"volume": 0.05, "trailing_pips": 10.000, "min_profit": 4.000},  # Goud afgestemd
    "XAGUSD":   {"volume": 0.04, "trailing_pips": 0.800,  "min_profit": 0.300},  # Zilver extra strak
    "XTIUSD":   {"volume": 0.50, "trailing_pips": 0.900,  "min_profit": 0.350}   # Olie finetune
}

MAGIC_NUMBER = 202609
MAX_BARS_HELD = 16  # Harde tijd-exit op basis van backtest data
ACTIEVE_POSITIES = {}

def bereken_macro_trend(symbool):
    """Controleert H4 EMA-50 voor de middellange trend"""
    rates = mt5.copy_rates_from_pos(symbool, mt5.TIMEFRAME_H4, 0, 60)
    if rates is None or len(rates) < 50: return None
    df = pd.DataFrame(rates)
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
    return "BULLISH" if df['close'].iloc[-1] > df['EMA_50'].iloc[-1] else "BEARISH"

def bereken_dynamische_sniper_grenzen(symbool):
    rates = mt5.copy_rates_from_pos(symbool, mt5.TIMEFRAME_H1, 0, 90)
    if rates is None or len(rates) < 30: return 35, 65  
    df = pd.DataFrame(rates)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    rsi_reeks = df['RSI'].dropna().values
    gemiddelde_rsi = np.mean(rsi_reeks)
    volatiliteit = np.std(rsi_reeks)
    
    buy_grens = gemiddelde_rsi - (1.95 * volatiliteit)
    sell_grens = gemiddelde_rsi + (1.95 * volatiliteit)
    return max(22, min(buy_grens, 38)), min(78, max(sell_grens, 66))

def beheer_smart_exit(symbool, ticket, order_type, settings):
    """Beheert de Breakeven Trigger, Trailing Stop en Time-Decay"""
    position = mt5.positions_get(ticket=ticket)
    if not position: return True
    
    pos = position[0]
    tick = mt5.symbol_info_tick(symbool)
    if not tick: return False
    
    digits = mt5.symbol_info(symbool).digits
    huidige_sl = pos.sl
    open_tijd = datetime.fromtimestamp(pos.time)
    uren_open = (datetime.now() - open_tijd).total_seconds() / 3600.0
    
    # 1. TIME-DECAY EXIT (Als de trade te lang blijft hangen)
    if uren_open > MAX_BARS_HELD:
        print(f"[⏱️ TIME EXIT] Trade {symbool} staat al {uren_open:.1f} uur open. Harde sluiting.")
        sluit_type = mt5.ORDER_TYPE_SELL if order_type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        stuur_sniper_order(symbool, pos.volume, sluit_type, "Time-Decay Close", ticket)
        return True

    # 2. PRO-TRAILING & BREAKEVEN LOGICA
    if order_type == mt5.ORDER_TYPE_BUY:
        winst_pips = tick.bid - pos.price_open
        if winst_pips > settings["min_profit"]:
            nieuwe_sl = round(tick.bid - settings["trailing_pips"], digits)
            # Als er nog geen SL is, zet hem op Breakeven (+2 pips voor kosten)
            if huidige_sl == 0.0:
                huidige_sl = round(pos.price_open + (settings["trailing_pips"] * 0.1), digits)
                mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": huidige_sl, "tp": pos.tp})
            # Glijdende trailing stop omhoog
            elif nieuwe_sl > huidige_sl:
                mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": nieuwe_sl, "tp": pos.tp})
                
    elif order_type == mt5.ORDER_TYPE_SELL:
        winst_pips = pos.price_open - tick.ask
        if winst_pips > settings["min_profit"]:
            nieuwe_sl = round(tick.ask + settings["trailing_pips"], digits)
            if huidige_sl == 0.0:
                huidige_sl = round(pos.price_open - (settings["trailing_pips"] * 0.1), digits)
                mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": huidige_sl, "tp": pos.tp})
            elif huidige_sl != 0.0 and nieuwe_sl < huidige_sl:
                mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": nieuwe_sl, "tp": pos.tp})
                
    return False

def stuur_sniper_order(symbool, volume, order_type, comment, position_ticket=None):
    tick = mt5.symbol_info_tick(symbool)
    if not tick: return False
    prijs = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbool,
        "volume": volume,
        "type": order_type,
        "price": prijs,
        "deviation": 15,
        "magic": MAGIC_NUMBER,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_RETURN,
    }
    if position_ticket is not None: request["position"] = position_ticket
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE: return result.order
    return False

# ====================================================================
# RUNTIME CORE
# ====================================================================
print("======================================================")
print("   SNIPER ENGINE v9.0: QUANT FINE-TUNED REVOLUTION    ")
print("======================================================")

if not mt5.initialize(): quit()

try:
    while True:
        nu_tijd = datetime.now().strftime("%H:%M:%S")
        
        for asset, settings in MARKET_CONFIG.items():
            mogelijke_namen = [asset, f"{asset}.", f"{asset}.cc", f"{asset[:3]}/{asset[3:]}"]
            symbool_naam = None
            for n in mogelijke_namen:
                if mt5.symbol_info(n) is not None: symbool_naam = n; break
            if symbool_naam is None: continue
            
            trend = bereken_macro_trend(symbool_naam)
            buy_rsi_dyn, sell_rsi_dyn = bereken_dynamische_sniper_grenzen(symbool_naam)
            
            # Haal live RSI op
            rates = mt5.copy_rates_from_pos(symbool_naam, mt5.TIMEFRAME_H1, 0, 30)
            if rates is None or len(rates) < 15: continue
            df_live = pd.DataFrame(rates)
            delta = df_live['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            live_rsi = (100 - (100 / (1 + (gain / loss)))).iloc[-1]
            
            if trend is None or np.isnan(live_rsi): continue
            status_trade = ACTIEVE_POSITIES.get(asset, {"type": "GEEN TRADES"})["type"]
            
            print(f"[{nu_tijd}] {symbool_naam:7} | RSI: {live_rsi:.2f} | Trend: {trend:8} | Status: {status_trade}")
            
            # ROUTER LOGICA
            if asset not in ACTIEVE_POSITIES:
                # Alleen LONG als de macro trend BULLISH is en RSI capituleert
                if trend == "BULLISH" and live_rsi < buy_rsi_dyn:
                    print(f"[🟢 TREND SNIPE LONG] {symbool_naam} matcht macro-trend. Open LONG...")
                    ticket = stuur_sniper_order(symbool_naam, settings['volume'], mt5.ORDER_TYPE_BUY, "Sniper v9 Long")
                    if ticket: ACTIEVE_POSITIES[asset] = {"type": "LONG", "ticket": ticket}
                
                # Alleen SHORT als de macro trend BEARISH is en RSI oververhit is
                elif trend == "BEARISH" and live_rsi > sell_rsi_dyn:
                    print(f"[🔴 TREND SNIPE SHORT] {symbool_naam} matcht macro-trend. Open SHORT...")
                    ticket = stuur_sniper_order(symbool_naam, settings['volume'], mt5.ORDER_TYPE_SELL, "Sniper v9 Short")
                    if ticket: ACTIEVE_POSITIES[asset] = {"type": "SHORT", "ticket": ticket}
            else:
                huidige_trade = ACTIEVE_POSITIES[asset]
                
                # Beheer exits (Breakeven / Trailing / Time-out)
                gesloten = beheer_smart_exit(symbool_naam, huidige_trade["ticket"], mt5.ORDER_TYPE_BUY if huidige_trade["type"] == "LONG" else mt5.ORDER_TYPE_SELL, settings)
                if gesclosed:
                    del ACTIEVE_POSITIES[asset]; continue
                
                # Wiskundige Take Profit via RSI-omkeer
                if huidige_trade["type"] == "LONG" and live_rsi > sell_rsi_dyn:
                    if stuur_sniper_order(symbool_naam, settings['volume'], mt5.ORDER_TYPE_SELL, "RSI TP Long", huidige_trade["ticket"]):
                        del ACTIEVE_POSITIES[asset]
                elif huidige_trade["type"] == "SHORT" and live_rsi < buy_rsi_dyn:
                    if stuur_sniper_order(symbool_naam, settings['volume'], mt5.ORDER_TYPE_BUY, "RSI TP Short", huidige_trade["ticket"]):
                        del ACTIEVE_POSITIES[asset]
                        
            time.sleep(0.05)
            
        print("-" * 75)
        time.sleep(30)

except KeyboardInterrupt:
    print("\n[*] Engine veilig gepauzeerd.")
finally:
    mt5.shutdown()