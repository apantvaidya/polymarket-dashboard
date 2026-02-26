from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from sqlalchemy import Column, Float, Integer, String, create_engine
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.orm import declarative_base, sessionmaker

from .models import BookSnapshot, Event

Base = declarative_base()


class SnapshotRow(Base):
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(Integer, nullable=False)
    event_id = Column(String, nullable=True)
    token_id = Column(String, nullable=False)
    best_bid = Column(Float, nullable=True)
    best_ask = Column(Float, nullable=True)
    mid = Column(Float, nullable=True)
    spread = Column(Float, nullable=True)
    levels_top_n = Column(SQLITE_JSON, nullable=True)


def _model_to_dict(obj) -> dict:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj.dict()


class EventLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(self, event: Event) -> None:
        payload = _model_to_dict(event)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")


class SnapshotStore:
    def __init__(self, jsonl_path: Optional[Path] = None, sqlite_path: Optional[Path] = None) -> None:
        self.jsonl_path = jsonl_path
        self.sqlite_path = sqlite_path
        self._session_factory = None

        if self.jsonl_path:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        if self.sqlite_path:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(f"sqlite:///{self.sqlite_path}")
            Base.metadata.create_all(engine)
            self._session_factory = sessionmaker(bind=engine)

    def write_snapshot(self, snapshot: BookSnapshot) -> None:
        payload = _model_to_dict(snapshot)
        if self.jsonl_path:
            with self.jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=True) + "\n")
        if self._session_factory:
            session = self._session_factory()
            row = SnapshotRow(
                ts=snapshot.ts,
                event_id=snapshot.event_id,
                token_id=snapshot.token_id,
                best_bid=snapshot.best_bid,
                best_ask=snapshot.best_ask,
                mid=snapshot.mid,
                spread=snapshot.spread,
                levels_top_n=snapshot.levels_top_n,
            )
            session.add(row)
            session.commit()
            session.close()
