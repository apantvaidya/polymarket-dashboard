from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Dict, List, Optional

from .models import BookSnapshot, Config
from .orderbook import OrderBook
from .polymarket_gamma import discover_soccer_markets
from .registry import Registry
from .storage import EventLogger, SnapshotStore
from .utils import get_logger, now_ms
from .ws_client import WSClient


def _parse_args() -> Config:
    parser = argparse.ArgumentParser(description="Polymarket soccer market ingestion")
    parser.add_argument("--query", type=str, default=None, help="Search string for match discovery")
    parser.add_argument("--event-id", type=str, default=None, help="Use an existing event_id")
    parser.add_argument("--log-events", type=str, default=None, help="Path to JSONL event log")
    parser.add_argument("--snapshot-every", type=int, default=None, help="Snapshot interval in seconds")
    parser.add_argument("--snapshot-jsonl", type=str, default=None, help="Path to JSONL snapshot log")
    parser.add_argument("--snapshot-sqlite", type=str, default=None, help="Path to SQLite snapshot DB")
    parser.add_argument("--levels", type=int, default=5, help="Top N levels for snapshots")
    parser.add_argument("--debug", action="store_true", help="Include raw messages in events")
    parser.add_argument("--max-runtime-seconds", type=int, default=None, help="Stop after N seconds")
    args = parser.parse_args()
    return Config(**vars(args))


def _select_registry_entry(query: str) -> Optional[str]:
    registry = Registry(Path("data/registry.json"))
    registry.load()
    entries = list(registry.events.values())
    if not entries:
        discover_soccer_markets(query)
        registry.load()
        entries = list(registry.events.values())
    if not entries:
        return None
    entries.sort(key=lambda e: sum(len(v) for v in e.token_ids_by_type.values()), reverse=True)
    return entries[0].event_id


def _load_token_ids(event_id: str) -> List[str]:
    registry = Registry(Path("data/registry.json"))
    registry.load()
    entry = registry.get(event_id)
    if not entry:
        return []
    token_ids: List[str] = []
    for ids in entry.token_ids_by_type.values():
        token_ids.extend(ids)
    return sorted(set(token_ids))


def _build_snapshot(event_id: Optional[str], token_id: str, ob: OrderBook, levels: int) -> BookSnapshot:
    best_bid = ob.best_bid()
    best_ask = ob.best_ask()
    mid = ob.mid()
    spread = ob.spread()
    levels_top_n = {
        "bids": ob.top_n_bids(levels),
        "asks": ob.top_n_asks(levels),
    }
    return BookSnapshot(
        ts=now_ms(),
        event_id=event_id,
        token_id=token_id,
        best_bid=best_bid,
        best_ask=best_ask,
        mid=mid,
        spread=spread,
        levels_top_n=levels_top_n,
    )


def main() -> None:
    config = _parse_args()
    logger = get_logger("market_edge.ingest", debug=config.debug)

    event_id = config.event_id
    if not event_id and config.query:
        event_id = _select_registry_entry(config.query)

    if not event_id:
        logger.error("No event_id found. Provide --event-id or --query.")
        return

    token_ids = _load_token_ids(event_id)
    if not token_ids:
        logger.error("No token_ids found for event_id %s", event_id)
        return

    event_logger = EventLogger(Path(config.log_events_path)) if config.log_events_path else None

    snapshot_jsonl = Path(config.snapshot_jsonl) if config.snapshot_jsonl else None
    if config.snapshot_every and not snapshot_jsonl and not config.snapshot_sqlite:
        snapshot_jsonl = Path("data/snapshots.jsonl")

    snapshot_store = SnapshotStore(
        jsonl_path=snapshot_jsonl,
        sqlite_path=Path(config.snapshot_sqlite) if config.snapshot_sqlite else None,
    )

    books: Dict[str, OrderBook] = {}
    last_snapshot_ms = 0

    def on_event(event) -> None:
        nonlocal last_snapshot_ms
        if event_logger:
            event_logger.log_event(event)

        if event.event_type in {"snapshot", "delta"}:
            if not event.token_id:
                return
            ob = books.setdefault(event.token_id, OrderBook())
            book_payload = event.payload.get("book", {})
            if event.event_type == "snapshot":
                ob.apply_snapshot(book_payload)
            else:
                ob.apply_delta(book_payload)

        if config.snapshot_every:
            now = now_ms()
            if now - last_snapshot_ms >= config.snapshot_every * 1000:
                for token_id, ob in books.items():
                    snapshot = _build_snapshot(event_id, token_id, ob, config.levels)
                    snapshot_store.write_snapshot(snapshot)
                last_snapshot_ms = now

    client = WSClient(
        token_ids=token_ids,
        event_id=event_id,
        debug=config.debug,
        max_runtime_seconds=config.max_runtime_seconds,
    )

    asyncio.run(client.run(on_event))


if __name__ == "__main__":
    main()
