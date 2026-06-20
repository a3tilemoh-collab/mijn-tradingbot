"""
==============================================================
  PEPPERSTONE DEMO - MT5 TEST BOT  |  Directe Koop Bot
  Doel: Verbinding testen + direct kopen zonder conditie
  Fase: TEST - geen echte logica, gewoon orderstroom valideren
==============================================================
"""

import MetaTrader5 as mt5
import time
from datetime import datetime

# ─────────────────────────────────────────────
#  INSTELLINGEN  ← pas hier aan
# ─────────────────────────────────────────────
SYMBOL      = "BTCUSD"      # Probeer ook: ETHUSD, LTCUSD
VOLUME      = 0.01          # Kleinste lotgrootte voor crypto
MAGIC       = 202406        # Uniek ID voor deze bot
COMMENT     = "TestBot_v1"  # Zichtbaar in MT5 history
SLUIT_NA    = 60            # Seconden waarna positie wordt gesloten (0 = nooit)
# ─────────────────────────────────────────────

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def verbinden():
    """Maak verbinding met MT5."""
    log("Verbinding maken met MetaTrader 5...")
    if not mt5.initialize():
        log(f"FOUT: Kan MT5 niet starten → {mt5.last_error()}")
        log("Tip: Zorg dat MT5 open staat en Algo Trading is ingeschakeld.")
        return False

    info = mt5.terminal_info()
    account = mt5.account_info()
    log(f"✓ MT5 verbonden | Build: {info.build}")
    log(f"✓ Account: {account.login} | Broker: {account.company}")
    log(f"✓ Saldo: ${account.balance:.2f} | Leverage: 1:{account.leverage}")
    return True

def symbool_voorbereiden(symbol):
    """Zorg dat het symbool actief is in MT5."""
    if not mt5.symbol_select(symbol, True):
        log(f"FOUT: Symbool {symbol} niet gevonden of niet beschikbaar.")
        log("Tip: Controleer in MT5 → Market Watch welke crypto-symbolen beschikbaar zijn.")
        return False

    info = mt5.symbol_info(symbol)
    if info is None:
        log(f"FOUT: Geen info voor {symbol}")
        return False

    log(f"✓ Symbool: {symbol} | Min lot: {info.volume_min} | Spread: {info.spread} punten")
    return True

def koop(symbol, volume):
    """Stuur direct een market-koop order."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        log(f"FOUT: Geen prijsdata voor {symbol}")
        return None

    prijs = tick.ask
    log(f"➜ Koop order: {symbol} | Volume: {volume} | Prijs: {prijs}")

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    symbol,
        "volume":    float(volume),
        "type":      mt5.ORDER_TYPE_BUY,
        "price":     prijs,
        "deviation": 20,           # max slippage in punten
        "magic":     MAGIC,
        "comment":   COMMENT,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    resultaat = mt5.order_send(request)

    if resultaat is None:
        log(f"FOUT: order_send gaf None → {mt5.last_error()}")
        return None

    if resultaat.retcode == mt5.TRADE_RETCODE_DONE:
        log(f"✓ ORDER GEVULD! Ticket: #{resultaat.order} | Prijs: {resultaat.price}")
        return resultaat.order
    else:
        log(f"✗ Order mislukt | Code: {resultaat.retcode} | Omschrijving: {resultaat.comment}")
        log("Veelvoorkomende codes:")
        log("  10027 = Algo Trading uitgeschakeld → zet 'AutoTrading' aan in MT5 toolbar")
        log("  10018 = Markt is gesloten (crypto is 24/7, check broker)")
        log("  10014 = Ongeldig volume (probeer 0.01)")
        return None

def sluit_positie(ticket):
    """Sluit een open positie op basis van ticket nummer."""
    posities = mt5.positions_get(ticket=ticket)
    if not posities:
        log(f"Positie #{ticket} niet gevonden (mogelijk al gesloten).")
        return

    pos = posities[0]
    tick = mt5.symbol_info_tick(pos.symbol)
    sluit_prijs = tick.bid  # voor verkoop (sluit long)

    log(f"➜ Sluit positie #{ticket} | Prijs: {sluit_prijs}")

    request = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    pos.symbol,
        "volume":    pos.volume,
        "type":      mt5.ORDER_TYPE_SELL,
        "position":  ticket,
        "price":     sluit_prijs,
        "deviation": 20,
        "magic":     MAGIC,
        "comment":   "Sluit_TestBot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    res = mt5.order_send(request)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log(f"✓ Positie gesloten | P&L zichtbaar in MT5 History")
    else:
        log(f"✗ Sluiten mislukt | Code: {res.retcode if res else 'None'}")

def toon_open_posities():
    """Laat zien welke posities open staan."""
    posities = mt5.positions_get(magic=MAGIC)
    if not posities:
        log("Geen open posities gevonden voor deze bot.")
        return
    log(f"─── Open posities ({len(posities)}) ───")
    for p in posities:
        winst = p.profit
        log(f"  #{p.ticket} | {p.symbol} | {p.volume} lot | P&L: ${winst:.2f}")

# ══════════════════════════════════════════════
#  HOOFDPROGRAMMA
# ══════════════════════════════════════════════
def main():
    print("=" * 54)
    print("  PEPPERSTONE DEMO - DIRECTE KOOP TEST BOT")
    print(f"  Symbool: {SYMBOL} | Volume: {VOLUME} lot")
    print("=" * 54)

    # Stap 1: Verbinden
    if not verbinden():
        return

    # Stap 2: Symbool activeren
    if not symbool_voorbereiden(SYMBOL):
        mt5.shutdown()
        return

    # Stap 3: Direct kopen
    ticket = koop(SYMBOL, VOLUME)

    if ticket:
        # Stap 4: Toon positie
        time.sleep(1)
        toon_open_posities()

        # Stap 5: Wacht en sluit (optioneel)
        if SLUIT_NA > 0:
            log(f"Wacht {SLUIT_NA} seconden... dan automatisch sluiten.")
            time.sleep(SLUIT_NA)
            sluit_positie(ticket)
        else:
            log("SLUIT_NA = 0 → positie blijft open. Sluit handmatig in MT5.")

    # Afsluiten
    mt5.shutdown()
    log("✓ MT5 verbinding gesloten. Bot klaar.")
    print("=" * 54)

if __name__ == "__main__":
    main()
