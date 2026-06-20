import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
from datetime import datetime

# ====================================================================
# INTRADAY MOMENTUM ENGINE v1.5 (FULL CRYPTO MATRIX UNLOCKED)
# ====================================================================
MARKET_CONFIG = {
    # --- DE CORE CRYPTO TOPPERS (24/7 LIVE) ---
    "BTCUSD":   {"volume": 0.20, "type": "CRYPTO", "trailing_pips": 80.0,   "min_volume_mult": 1.2}, 
    "ETHUSD":   {"volume": 0.20, "type": "CRYPTO", "trailing_pips": 40.0,   "min_volume_mult": 1.2},
    "BNBUSD":   {"volume": 3.0,  "type": "CRYPTO", "trailing_pips": 8.0,    "min_volume_mult": 1.2},
    "SOLUSD":   {"volume": 3.0,  "type": "CRYPTO", "trailing_pips": 3.5,    "min_volume_mult": 1.2},
    "XRPUSD":   {"volume": 50.0, "type": "CRYPTO", "trailing_pips": 0.0150, "min_volume_mult": 1.2}, 
    "ADAUSD":   {"volume": 50.0, "type": "CRYPTO", "trailing_pips": 0.0150, "min_volume_mult": 1.2}, 
    
    # --- PEPPERSTONE MID-CAPS & LAYER-1'S (Toegevoegd conform verzoek) ---
    "LTCUSD":   {"volume": 2.0,  "type": "CRYPTO", "trailing_pips": 2.50,   "min_volume_mult": 1.2}, # Litecoin
    "LINKUSD":  {"volume": 10.0, "type": "CRYPTO", "trailing_pips": 0.35,   "min_volume_mult": 1.2}, # Chainlink
    "AVAXUSD":  {"volume": 5.0,  "type": "CRYPTO", "trailing_pips": 0.80,   "min_volume_mult": 1.2}, # Avalanche
    "DOTUSD":   {"volume": 10.0, "type": "CRYPTO", "trailing_pips": 0.15,   "min_volume_mult": 1.2}, # Polkadot
    "UNIUSD":   {"volume": 15.0, "type": "CRYPTO", "trailing_pips": 0.18,   "min_volume_mult": 1.2}, # Uniswap
    "XLMUSD":   {"volume": 100.0,"type": "CRYPTO", "trailing_pips": 0.0080, "min_volume_mult": 1.2}, # Stellar Lumens
    
    # --- MEME COINS (Ultra high momentum) ---
    "DOGEUSD":  {"volume": 100.0,"type": "CRYPTO", "trailing_pips": 0.0080, "min_volume_mult": 1.2}, # Dogecoin
    "SHIBUSD":  {"volume": 500.0,"type": "CRYPTO", "trailing_pips": 0.0000020, "min_volume_mult": 1.2}, # Shiba Inu
    
    # --- FOREX & METALS (Inactief tijdens het weekend via automatische Lock) ---
    "EURUSD":   {"volume": 0.50, "type": "FOREX",  "trailing_pips": 0.0025, "min_volume_mult": 1.3}, 
    "GBPUSD":   {"volume": 0.50, "type": "FOREX",  "trailing_pips": 0.0025, "min_volume_mult": 1.3},
    "USDJPY":   {"volume": 0.50, "type": "FOREX",  "trailing_pips": 0.250,  "min_volume_mult": 1.3},
    "XAUUSD":   {"volume": 0.05, "type": "METAL",  "trailing_pips": 5.000,  "min_volume_mult": 1.3}, 
    "XAGUSD":   {"volume": 0.04, "type": "METAL",  "trailing_pips": 0.400,  "min_volume_mult": 1.4}
}

MAGIC_NUMBER = 999555
ACTIEVE_POSITIES = {}

def haal_market_data(symbool):
    """Haalt M5 data op en berekent EMAs en Volume Spikes"""
    rates = mt5.copy_rates_from_pos(symbool, mt5.TIMEFRAME_M5, 0, 50)
    if rates is None or len(rates) < 30: return None
    
    df = pd.DataFrame(rates)
    
    if 'real_volume' in df.columns and df['real_volume'].max() > 0:
        df['intraday_volume'] = df['real_volume']
    else:
        df['intraday_volume'] = df['tick_volume']
        
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['Vol_MA'] = df['intraday_volume'].rolling(window=20).mean()
    
    return df.iloc[-1], df.iloc[-2]

def beheer_intraday_trailing(symbool, ticket, order_type, trailing_pips):
    """Scherpe meereizende stop om intraday winsten direct te harken"""
    position = mt5.positions_get(ticket=ticket)
    if not position or len(position) == 0: return
    pos = position[0]
    tick = mt5.symbol_info_tick(symbool)
    if not tick: return
    
    huidige_sl = pos.sl
    digits = mt5.symbol_info(symbool).digits
    
    if order_type == mt5.ORDER_TYPE_BUY:
        nieuwe_sl = round(tick.bid - trailing_pips, digits)
        if huidige_sl == 0.0 or nieuwe_sl > huidige_sl:
            if tick.bid > (pos.price_open + trailing_pips):
                mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": nieuwe_sl, "tp": pos.tp})
                
    elif order_type == mt5.ORDER_TYPE_SELL:
        nieuwe_sl = round(tick.ask + trailing_pips, digits)
        if huidige_sl == 0.0 or nieuwe_sl < huidige_sl:
            if tick.ask < (pos.price_open - trailing_pips):
                mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": nieuwe_sl, "tp": pos.tp})

def stuur_market_order(symbool, volume, order_type, comment, position_ticket=None):
    tick = mt5.symbol_info_tick(symbool)
    if not tick: return False
    prijs = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbool,
        "volume": volume,
        "type": order_type,
        "price": prijs,
        "deviation": 10,
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
# RUNTIME MATRIX LIVE
# ====================================================================
print("======================================================")
print("   INTRADAY MOMENTUM BOT v1.5: MASSIVE CRYPTO ARRAY   ")
print("======================================================")

if not mt5.initialize(): 
    print("[-] MT5 Connectie Fout."); quit()

try:
    while True:
        nu_tijd = datetime.now().strftime("%H:%M:%S")
        nu_uur = datetime.now().hour
        
        for asset, settings in MARKET_CONFIG.items():
            mogelijke_namen = [asset, f"{asset}.", f"{asset}.cc", f"{asset[:3]}/{asset[3:]}"]
            symbool_naam = None
            for n in mogelijke_namen:
                if mt5.symbol_info(n) is not None: symbool_naam = n; break
            if symbool_naam is None: continue
            
            # Categorie 4: Macro Lock (Skip Forex/Metalen automatisch in het weekend)
            if settings["type"] in ["FOREX", "METAL"] and (datetime.now().weekday() == 4 and nu_uur >= 21 or datetime.now().weekday() in [5, 6]):
                continue
                
            data_live, data_vorige = haal_market_data(symbool_naam)
            if data_live is None: continue
            
            ema_9_nu, ema_21_nu = data_live['EMA_9'], data_live['EMA_21']
            ema_9_old, ema_21_old = data_vorige['EMA_9'], data_vorige['EMA_21']
            live_volume = data_live['intraday_volume']
            volume_gemiddeld = data_live['Vol_MA']
            
            status_trade = ACTIEVE_POSITIES.get(asset, {"type": "GEEN TRADES"})["type"]
            print(f"[{nu_tijd}] {symbool_naam:7} | Vol: {int(live_volume)}/{int(volume_gemiddeld)} | EMA9: {ema_9_nu:.4f} | Status: {status_trade}")
            
            # TRADE LOGICA
            if asset not in ACTIEVE_POSITIES:
                if live_volume > (volume_gemiddeld * settings["min_volume_mult"]):
                    
                    # Bullish Cross (EMA9 kruist boven EMA21)
                    if ema_9_old <= ema_21_old and ema_9_nu > ema_21_nu:
                        print(f"[🚀 MOMENTUM BUY] {symbool_naam} Volume bevestigd! Open LONG...")
                        ticket = stuur_market_order(symbool_naam, settings['volume'], mt5.ORDER_TYPE_BUY, "M5 Momentum Long")
                        if ticket: ACTIEVE_POSITIES[asset] = {"type": "LONG", "ticket": ticket}
                            
                    # Bearish Cross (EMA9 kruist onder EMA21)
                    elif ema_9_old >= ema_21_old and ema_9_nu < ema_21_nu:
                        print(f"[💥 MOMENTUM SELL] {symbool_naam} Volume bevestigd! Open SHORT...")
                        ticket = stuur_market_order(symbool_naam, settings['volume'], mt5.ORDER_TYPE_SELL, "M5 Momentum Short")
                        if ticket: ACTIEVE_POSITIES[asset] = {"type": "SHORT", "ticket": ticket}
            else:
                huidige_trade = ACTIEVE_POSITIES[asset]
                pos_info = mt5.positions_get(ticket=huidige_trade["ticket"])
                
                if not pos_info or len(pos_info) == 0:
                    print(f"[i] Momentum trade {symbool_naam} gesloten via Trailing of handmatig.")
                    del ACTIEVE_POSITIES[asset]; continue
                
                # Direct momentum close bij tegen-kruising
                if huidige_trade["type"] == "LONG" and ema_9_nu < ema_21_nu:
                    print(f"[💰 MOMENTUM EXIT] Trend keert om. Sluit LONG voor {symbool_naam}...")
                    if stuur_market_order(symbool_naam, settings['volume'], mt5.ORDER_TYPE_SELL, "Momentum Close", huidige_trade["ticket"]):
                        del ACTIEVE_POSITIES[asset]
                elif huidige_trade["type"] == "SHORT" and ema_9_nu > ema_21_nu:
                    print(f"[💰 MOMENTUM EXIT] Trend keert om. Sluit SHORT voor {symbool_naam}...")
                    if stuur_market_order(symbool_naam, settings['volume'], mt5.ORDER_TYPE_BUY, "Momentum Close", huidige_trade["ticket"]):
                        del ACTIEVE_POSITIES[asset]
                else:
                    beheer_intraday_trailing(symbool_naam, huidige_trade["ticket"], mt5.ORDER_TYPE_BUY if huidige_trade["type"] == "LONG" else mt5.ORDER_TYPE_SELL, settings['trailing_pips'])
                    
            time.sleep(0.05)
            
        print("-" * 75)
        time.sleep(10)  

except KeyboardInterrupt:
    print("\n[*] Intraday Momentum Engine gepauzeerd.")
finally:
    mt5.shutdown()