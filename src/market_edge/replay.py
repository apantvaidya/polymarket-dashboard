from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Dict

from .models import Event
from .orderbook import OrderBook


def _parse_args():
    parser = argparse.ArgumentParser(description="Replay Polymarket event logs")
    parser.add_argument("--path", type=str, required=True, help="Path to events.jsonl")
    parser.add_argument("--levels", type=int, default=5, help="Top N levels to display")
    parser.add_argument("--speed", type=float, default=1.0, help="Replay speed multiplier")
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()


def _render(books: Dict[str, OrderBook], levels: int) -> None:
    print("\033[2J\033[H", end="")
    print("Replay view (token_id | best_bid | best_ask | mid | spread)")
    for token_id, ob in books.items():
        best_bid = ob.best_bid()
        best_ask = ob.best_ask()
        mid = ob.mid()
        spread = ob.spread()
        print(f"{token_id} | {best_bid} | {best_ask} | {mid} | {spread}")
        print(f"  bids: {ob.top_n_bids(levels)}")
        print(f"  asks: {ob.top_n_asks(levels)}")


def main() -> None:
    args = _parse_args()
    path = Path(args.path)
    books: Dict[str, OrderBook] = {}

    last_ts = None
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        event = Event(**data)

        if last_ts is not None:
            delta_ms = max(event.ts_local_ms - last_ts, 0)
            time.sleep((delta_ms / 1000.0) / max(args.speed, 0.01))
        last_ts = event.ts_local_ms

        if event.event_type in {"snapshot", "delta"}:
            if not event.token_id:
                continue
            ob = books.setdefault(event.token_id, OrderBook())
            book_payload = event.payload.get("book", {})
            if event.event_type == "snapshot":
                ob.apply_snapshot(book_payload)
            else:
                ob.apply_delta(book_payload)
            _render(books, args.levels)


if __name__ == "__main__":
    main()
