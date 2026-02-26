from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Outcome(BaseModel):
    label: str
    token_id: str


class MarketMeta(BaseModel):
    market_id: str
    question: str
    event_slug: Optional[str] = None
    event_name: Optional[str] = None
    outcomes: List[Outcome]
    start_time: Optional[str] = None


class Event(BaseModel):
    ts_local_ms: int
    session_id: str
    event_type: str  # snapshot | delta | trade | heartbeat | error | subscribed
    event_id: Optional[str] = None
    market_id: Optional[str] = None
    token_id: Optional[str] = None
    side: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[float] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    raw: Optional[Dict[str, Any]] = None


class Quote(BaseModel):
    token_id: str
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    mid: Optional[float] = None
    last: Optional[float] = None
    ts: int


class BookSnapshot(BaseModel):
    ts: int
    event_id: Optional[str] = None
    token_id: str
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    mid: Optional[float] = None
    spread: Optional[float] = None
    levels_top_n: Dict[str, List[List[float]]] = Field(default_factory=dict)


class Config(BaseModel):
    query: Optional[str] = None
    event_id: Optional[str] = None
    log_events_path: Optional[str] = None
    snapshot_every: Optional[int] = None
    snapshot_jsonl: Optional[str] = None
    snapshot_sqlite: Optional[str] = None
    levels: int = 5
    debug: bool = False
    max_runtime_seconds: Optional[int] = None
