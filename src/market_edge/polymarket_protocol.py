from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .models import Event


def _now_ms() -> int:
    return int(time.time() * 1000)


def _get_nested(d: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for key in keys:
        if key in d:
            return d[key]
    return None


def _normalize_levels(levels: List[Any]) -> List[List[float]]:
    normalized: List[List[float]] = []
    for level in levels:
        if isinstance(level, dict):
            price = level.get("price")
            size = level.get("size")
        else:
            price, size = level
        if price is None or size is None:
            continue
        normalized.append([float(price), float(size)])
    return normalized


def _extract_book(raw: Dict[str, Any]) -> Dict[str, Any]:
    if "bids" in raw or "asks" in raw:
        return {
            "bids": _normalize_levels(raw.get("bids", [])),
            "asks": _normalize_levels(raw.get("asks", [])),
        }
    data = raw.get("data") or {}
    if "bids" in data or "asks" in data:
        return {
            "bids": _normalize_levels(data.get("bids", [])),
            "asks": _normalize_levels(data.get("asks", [])),
        }
    if "buys" in raw or "sells" in raw:
        return {
            "bids": _normalize_levels(raw.get("buys", [])),
            "asks": _normalize_levels(raw.get("sells", [])),
        }
    return {}


def _event(
    *,
    session_id: str,
    event_type: str,
    event_id: Optional[str],
    token_id: Optional[str],
    market_id: Optional[str],
    price: Optional[float],
    quantity: Optional[float],
    side: Optional[str],
    payload: Dict[str, Any],
    debug: bool,
    raw: Dict[str, Any],
) -> Event:
    return Event(
        ts_local_ms=_now_ms(),
        session_id=session_id,
        event_type=event_type,
        event_id=event_id,
        market_id=market_id,
        token_id=token_id,
        side=side,
        price=price,
        quantity=quantity,
        payload=payload,
        raw=raw if debug else None,
    )


def normalize_ws_message(
    raw: Dict[str, Any],
    session_id: str,
    event_id: Optional[str] = None,
    debug: bool = False,
) -> List[Event]:
    raw_event_type = str(_get_nested(raw, ["event_type", "type", "event", "eventType"]) or "").lower()
    action = str(raw.get("action") or raw.get("op") or "").lower()

    if raw_event_type in {"subscribed", "subscribe", "subscription"}:
        return [
            _event(
                session_id=session_id,
                event_type="subscribed",
                event_id=event_id,
                token_id=None,
                market_id=None,
                price=None,
                quantity=None,
                side=None,
                payload={},
                debug=debug,
                raw=raw,
            )
        ]
    if raw_event_type in {"heartbeat", "ping", "pong"}:
        return [
            _event(
                session_id=session_id,
                event_type="heartbeat",
                event_id=event_id,
                token_id=None,
                market_id=None,
                price=None,
                quantity=None,
                side=None,
                payload={},
                debug=debug,
                raw=raw,
            )
        ]
    if raw_event_type in {"error", "err"}:
        return [
            _event(
                session_id=session_id,
                event_type="error",
                event_id=event_id,
                token_id=None,
                market_id=None,
                price=None,
                quantity=None,
                side=None,
                payload={"message": raw.get("message")},
                debug=debug,
                raw=raw,
            )
        ]

    market_id = raw.get("market") or raw.get("marketId") or raw.get("market_id")
    token_id = raw.get("asset_id") or raw.get("tokenId") or raw.get("token_id")

    if raw_event_type in {"book", "snapshot"} or action == "snapshot":
        book = _extract_book(raw)
        return [
            _event(
                session_id=session_id,
                event_type="snapshot",
                event_id=event_id,
                token_id=str(token_id) if token_id is not None else None,
                market_id=str(market_id) if market_id is not None else None,
                price=None,
                quantity=None,
                side=None,
                payload={"book": book},
                debug=debug,
                raw=raw,
            )
        ]

    if raw_event_type in {"price_change", "delta"}:
        changes = raw.get("price_changes") or raw.get("changes") or []
        if not changes:
            book = _extract_book(raw)
            if book:
                return [
                    _event(
                        session_id=session_id,
                        event_type="delta",
                        event_id=event_id,
                        token_id=str(token_id) if token_id is not None else None,
                        market_id=str(market_id) if market_id is not None else None,
                        price=None,
                        quantity=None,
                        side=None,
                        payload={"book": book},
                        debug=debug,
                        raw=raw,
                    )
                ]
        events: List[Event] = []
        for change in changes:
            asset_id = change.get("asset_id") or token_id
            side = str(change.get("side") or "").upper()
            price = change.get("price")
            size = change.get("size")
            if side == "BUY":
                book = {"bids": [[float(price), float(size)]], "asks": []}
            elif side == "SELL":
                book = {"bids": [], "asks": [[float(price), float(size)]]}
            else:
                book = {}
            events.append(
                _event(
                    session_id=session_id,
                    event_type="delta",
                    event_id=event_id,
                    token_id=str(asset_id) if asset_id is not None else None,
                    market_id=str(market_id) if market_id is not None else None,
                    price=float(price) if price is not None else None,
                    quantity=float(size) if size is not None else None,
                    side=side if side else None,
                    payload={"book": book},
                    debug=debug,
                    raw=raw,
                )
            )
        return events

    if raw_event_type in {"last_trade_price", "trade"}:
        price = raw.get("price")
        size = raw.get("size")
        side = raw.get("side")
        return [
            _event(
                session_id=session_id,
                event_type="trade",
                event_id=event_id,
                token_id=str(token_id) if token_id is not None else None,
                market_id=str(market_id) if market_id is not None else None,
                price=float(price) if price is not None else None,
                quantity=float(size) if size is not None else None,
                side=str(side) if side is not None else None,
                payload={"price": price, "quantity": size, "side": side},
                debug=debug,
                raw=raw,
            )
        ]

    if raw_event_type in {"best_bid_ask", "tick_size_change", "new_market", "market_resolved"}:
        return [
            _event(
                session_id=session_id,
                event_type="delta",
                event_id=event_id,
                token_id=str(token_id) if token_id is not None else None,
                market_id=str(market_id) if market_id is not None else None,
                price=None,
                quantity=None,
                side=None,
                payload={"info": raw},
                debug=debug,
                raw=raw,
            )
        ]

    book = _extract_book(raw)
    if book:
        return [
            _event(
                session_id=session_id,
                event_type="delta",
                event_id=event_id,
                token_id=str(token_id) if token_id is not None else None,
                market_id=str(market_id) if market_id is not None else None,
                price=None,
                quantity=None,
                side=None,
                payload={"book": book},
                debug=debug,
                raw=raw,
            )
        ]

    return [
        _event(
            session_id=session_id,
            event_type="error",
            event_id=event_id,
            token_id=str(token_id) if token_id is not None else None,
            market_id=str(market_id) if market_id is not None else None,
            price=None,
            quantity=None,
            side=None,
            payload={"raw_event_type": raw_event_type},
            debug=debug,
            raw=raw,
        )
    ]
