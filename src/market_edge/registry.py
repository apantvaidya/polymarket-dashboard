from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional


def slugify(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")


@dataclass
class EventRegistryEntry:
    event_id: str
    match_name: str
    market_ids: List[str]
    token_ids_by_type: Dict[str, List[str]]
    market_ids_by_type: Dict[str, List[str]]
    market_names_by_type: Dict[str, List[str]]
    start_time: Optional[str] = None


class Registry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.events: Dict[str, EventRegistryEntry] = {}

    def load(self) -> None:
        if not self.path.exists():
            self.events = {}
            return
        data = json.loads(self.path.read_text())
        events: Dict[str, EventRegistryEntry] = {}
        for k, v in data.get("events", {}).items():
            if "market_ids_by_type" not in v:
                v["market_ids_by_type"] = {}
            if "market_names_by_type" not in v:
                v["market_names_by_type"] = {}
            events[k] = EventRegistryEntry(**v)
        self.events = events

    def save(self) -> None:
        payload = {"events": {k: asdict(v) for k, v in self.events.items()}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2))

    def upsert(self, entry: EventRegistryEntry) -> None:
        self.events[entry.event_id] = entry

    def get(self, event_id: str) -> Optional[EventRegistryEntry]:
        return self.events.get(event_id)

    def build_event_id(self, match_name: str, start_time: Optional[str]) -> str:
        date_part = None
        if start_time:
            date_part = start_time.split("T")[0]
        base = match_name
        if date_part:
            base = f"{match_name} {date_part}"
        return slugify(base)
