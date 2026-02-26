from __future__ import annotations

from typing import Dict, Iterable, List, Tuple, Optional


class OrderBook:
    def __init__(self) -> None:
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}

    def apply_snapshot(self, snapshot: Dict[str, Iterable[Iterable[float]]]) -> None:
        self.bids = {}
        self.asks = {}
        self._apply_levels(self.bids, snapshot.get("bids", []))
        self._apply_levels(self.asks, snapshot.get("asks", []))

    def apply_delta(self, delta: Dict[str, Iterable[Iterable[float]]]) -> None:
        self._apply_levels(self.bids, delta.get("bids", []))
        self._apply_levels(self.asks, delta.get("asks", []))

    def _apply_levels(self, book: Dict[float, float], levels: Iterable[Iterable[float]]) -> None:
        for level in levels:
            price, qty = self._parse_level(level)
            if qty <= 0:
                if price in book:
                    del book[price]
                continue
            book[price] = qty

    def _parse_level(self, level: Iterable[float]) -> Tuple[float, float]:
        price, qty = level
        return float(price), float(qty)

    def best_bid(self) -> Optional[float]:
        if not self.bids:
            return None
        return max(self.bids.keys())

    def best_ask(self) -> Optional[float]:
        if not self.asks:
            return None
        return min(self.asks.keys())

    def mid(self) -> Optional[float]:
        best_bid = self.best_bid()
        best_ask = self.best_ask()
        if best_bid is None or best_ask is None:
            return None
        return (best_bid + best_ask) / 2.0

    def spread(self) -> Optional[float]:
        best_bid = self.best_bid()
        best_ask = self.best_ask()
        if best_bid is None or best_ask is None:
            return None
        return best_ask - best_bid

    def top_n_bids(self, n: int) -> List[List[float]]:
        levels = sorted(self.bids.items(), key=lambda x: x[0], reverse=True)
        return [[price, qty] for price, qty in levels[:n]]

    def top_n_asks(self, n: int) -> List[List[float]]:
        levels = sorted(self.asks.items(), key=lambda x: x[0])
        return [[price, qty] for price, qty in levels[:n]]
