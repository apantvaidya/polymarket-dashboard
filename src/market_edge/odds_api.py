from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

from .registry import Registry

ODDS_API_BASE = "https://api.the-odds-api.com/v4"


@dataclass
class OddsOutcome:
    name: str
    price: float
    point: Optional[float] = None


@dataclass
class OddsRecord:
    ts_ms: int
    sport: str
    event_id: str
    odds_event_id: str
    home_team: str
    away_team: str
    commence_time: Optional[str]
    market: str
    bookmaker: str
    last_update: Optional[str]
    outcomes: List[OddsOutcome]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso_to_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _normalize_team(name: str) -> str:
    name = name.lower()
    name = name.replace("&", "and")
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    tokens = [
        t
        for t in name.split()
        if t not in {"fc", "afc", "cf", "sc", "the", "club", "de", "ac", "cfc"}
    ]
    return " ".join(tokens)


def _split_match_name(match_name: str) -> Optional[Tuple[str, str]]:
    for sep in (" vs ", " v ", " vs. ", " v. "):
        if sep in match_name.lower():
            left, right = match_name.split(sep, 1)
            return left.strip(), right.strip()
    return None


def _build_registry_index(registry: Registry) -> Dict[Tuple[str, str], List[str]]:
    index: Dict[Tuple[str, str], List[str]] = {}
    for event_id, entry in registry.events.items():
        parts = _split_match_name(entry.match_name)
        if not parts:
            continue
        home, away = parts
        key = tuple(sorted([_normalize_team(home), _normalize_team(away)]))
        index.setdefault(key, []).append(event_id)
    return index


def _match_event_id(
    registry: Registry,
    index: Dict[Tuple[str, str], List[str]],
    home_team: str,
    away_team: str,
    commence_time: Optional[str],
) -> Optional[str]:
    key = tuple(sorted([_normalize_team(home_team), _normalize_team(away_team)]))
    candidates = index.get(key, [])
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # If multiple, try to pick the closest by start_time.
    target_dt = _iso_to_dt(commence_time)
    if not target_dt:
        return candidates[0]
    best_id = candidates[0]
    best_delta = None
    for event_id in candidates:
        entry = registry.get(event_id)
        if not entry or not entry.start_time:
            continue
        entry_dt = _iso_to_dt(entry.start_time)
        if not entry_dt:
            continue
        delta = abs((entry_dt - target_dt).total_seconds())
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_id = event_id
    return best_id


def _write_jsonl(path: Path, rows: Iterable[OddsRecord]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            payload = asdict(row)
            payload["outcomes"] = [asdict(o) for o in row.outcomes]
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
            count += 1
    return count


class OddsApiClient:
    def __init__(self, api_key: str, base_url: str = ODDS_API_BASE, timeout_s: int = 20) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.session = requests.Session()

    def list_events(self, sport: str) -> List[Dict]:
        url = f"{self.base_url}/sports/{sport}/events"
        resp = self.session.get(url, params={"apiKey": self.api_key, "dateFormat": "iso"}, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    def event_odds(
        self,
        sport: str,
        event_id: str,
        regions: str,
        markets: str,
        bookmakers: str,
        odds_format: str = "decimal",
    ) -> Dict:
        url = f"{self.base_url}/sports/{sport}/events/{event_id}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": markets,
            "bookmakers": bookmakers,
            "oddsFormat": odds_format,
            "dateFormat": "iso",
        }
        resp = self.session.get(url, params=params, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()


def fetch_pinnacle_odds(
    registry_path: Path,
    out_path: Path,
    api_key: str,
    sport: str = "soccer_epl",
    regions: str = "uk,eu,us",
    markets: str = "h2h,h2h_3_way,spreads,totals,btts",
    bookmakers: str = "pinnacle",
    event_id: Optional[str] = None,
    registry_event_id: Optional[str] = None,
) -> int:
    registry = Registry(registry_path)
    registry.load()
    index = _build_registry_index(registry)

    client = OddsApiClient(api_key=api_key)
    if event_id:
        events = [{"id": event_id}]
    else:
        events = client.list_events(sport)

    records: List[OddsRecord] = []
    for event in events:
        odds_event_id = str(event.get("id") or "")
        home_team = str(event.get("home_team") or "")
        away_team = str(event.get("away_team") or "")
        commence_time = event.get("commence_time")
        if not odds_event_id or not home_team or not away_team:
            # If we were given an explicit event_id, allow odds fetch even without
            # the event list metadata (team names). We'll still try to map to registry
            # via team names if present, otherwise we'll skip event_id mapping.
            if not event_id:
                continue

        resolved_event_id = registry_event_id
        if not resolved_event_id and home_team and away_team:
            resolved_event_id = _match_event_id(
                registry,
                index,
                home_team=home_team,
                away_team=away_team,
                commence_time=commence_time,
            )
        if not resolved_event_id:
            # If we cannot map, we still log with the odds event id only.
            resolved_event_id = ""

        odds_payload = client.event_odds(
            sport=sport,
            event_id=odds_event_id,
            regions=regions,
            markets=markets,
            bookmakers=bookmakers,
        )
        for bookmaker in odds_payload.get("bookmakers", []):
            if str(bookmaker.get("key")) != bookmakers:
                continue
            last_update = bookmaker.get("last_update")
            for market in bookmaker.get("markets", []):
                market_key = str(market.get("key") or "")
                outcomes = []
                for outcome in market.get("outcomes", []):
                    name = str(outcome.get("name") or "")
                    price = outcome.get("price")
                    point = outcome.get("point")
                    if not name or price is None:
                        continue
                    outcomes.append(OddsOutcome(name=name, price=float(price), point=point))
                if not market_key or not outcomes:
                    continue
                # Write one record per outcome to make downstream usage and counts clear.
                for outcome in outcomes:
                    records.append(
                        OddsRecord(
                            ts_ms=_now_ms(),
                            sport=sport,
                            event_id=resolved_event_id,
                            odds_event_id=odds_event_id,
                            home_team=home_team,
                            away_team=away_team,
                            commence_time=commence_time,
                            market=market_key,
                            bookmaker=bookmakers,
                            last_update=last_update,
                            outcomes=[outcome],
                        )
                    )

    return _write_jsonl(out_path, records)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Pinnacle odds via The Odds API")
    parser.add_argument("--registry", type=str, default="data/registry.json")
    parser.add_argument("--out", type=str, default="data/odds.jsonl")
    parser.add_argument("--sport", type=str, default="soccer_epl")
    parser.add_argument("--regions", type=str, default="uk,eu,us")
    parser.add_argument(
        "--markets",
        type=str,
        default="h2h,h2h_3_way,spreads,totals,btts",
        help="Comma-delimited market keys",
    )
    parser.add_argument("--bookmakers", type=str, default="pinnacle")
    parser.add_argument("--event-id", type=str, default=None, help="Optional Odds API event id")
    parser.add_argument("--registry-event-id", type=str, default=None, help="Optional Polymarket event id")
    parser.add_argument("--api-key", type=str, default=None, help="Avoid using this; prefer ODDS_API_KEY")
    parser.add_argument("--api-key-env", type=str, default="ODDS_API_KEY")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    api_key = args.api_key or os.getenv(args.api_key_env)
    if not api_key:
        raise SystemExit(f"Missing API key. Set {args.api_key_env} or pass --api-key.")

    count = fetch_pinnacle_odds(
        registry_path=Path(args.registry),
        out_path=Path(args.out),
        api_key=api_key,
        sport=args.sport,
        regions=args.regions,
        markets=args.markets,
        bookmakers=args.bookmakers,
        event_id=args.event_id,
        registry_event_id=args.registry_event_id,
    )
    print(f"Wrote {count} odds records to {args.out}")


if __name__ == "__main__":
    main()
