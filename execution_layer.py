# ============================================================
#  UniversalBot - execution_layer.py
#  Order plaatsing en beheer via MetaTrader 5
# ============================================================

import MetaTrader5 as mt5
from config import RISK, MT5
import logging

logger = logging.getLogger(__name__)


def place_order(symbol: str, direction: str, lot: float, sl: float, tp: float) -> bool:
    """
    Plaatst een market order.
    direction: 'BUY' of 'SELL'
    Returns True bij succes.
    """
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        logger.error(f"Geen tick data voor {symbol}")
        return False

    price      = tick.ask if direction == "BUY" else tick.bid
    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL

    request = {
        "action":      mt5.TRADE_ACTION_DEAL,
        "symbol":      symbol,
        "volume":      lot,
        "type":        order_type,
        "price":       price,
        "sl":          round(sl, mt5.symbol_info(symbol).digits),
        "tp":          round(tp, mt5.symbol_info(symbol).digits),
        "deviation":   MT5["deviation"],
        "magic":       MT5["magic_number"],
        "comment":     MT5["comment"],
        "type_time":   mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)

    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        code = result.retcode if result else "None"
        logger.error(f"Order mislukt voor {symbol}: retcode={code}")
        return False

    logger.info(f"✅ {direction} {symbol} | lot={lot:.2f} | SL={sl:.5f} | TP={tp:.5f} | ticket={result.order}")
    return True


def close_all_positions(symbol: str = None):
    """
    Sluit alle open posities (optioneel gefilterd op symbol).
    """
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    if not positions:
        return

    for pos in positions:
        direction  = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick       = mt5.symbol_info_tick(pos.symbol)
        close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

        request = {
            "action":      mt5.TRADE_ACTION_DEAL,
            "symbol":      pos.symbol,
            "volume":      pos.volume,
            "type":        direction,
            "position":    pos.ticket,
            "price":       close_price,
            "deviation":   MT5["deviation"],
            "magic":       MT5["magic_number"],
            "comment":     "close " + MT5["comment"],
            "type_time":   mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"🔒 Gesloten: {pos.symbol} ticket={pos.ticket}")
        else:
            logger.warning(f"⚠️ Sluiten mislukt: {pos.symbol} ticket={pos.ticket}")


def get_open_positions(symbol: str = None) -> list:
    """
    Geeft lijst van open posities terug.
    """
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    return list(positions) if positions else []


def already_has_position(symbol: str) -> bool:
    """
    Returns True als er al een open positie is voor dit symbol.
    """
    return len(get_open_positions(symbol)) > 0
