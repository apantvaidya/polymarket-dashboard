from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from .models import MarketMeta, Outcome
from .registry import EventRegistryEntry, Registry

GAMMA_BASE = "https://gamma-api.polymarket.com"


class GammaClient:
    def __init__(self, base_url: str = GAMMA_BASE, timeout_s: int = 10) -> None:
        self.base_url = base_url
        self.timeout_s = timeout_s
        self.session = requests.Session()

    def public_search(self, query: str, limit: int = 50) -> Dict[str, Any]:
        url = f"{self.base_url}/public-search"
        # Gamma search expects `q` in recent docs; fall back to `query` for compatibility.
        for params in ({"q": query, "limit_per_type": limit}, {"query": query, "limit": limit}):
            resp = self.session.get(url, params=params, timeout=self.timeout_s)
            try:
                resp.raise_for_status()
            except requests.HTTPError:
                continue
            return resp.json()
        return {}

    def list_events(
        self,
        limit: int = 200,
        active: bool = True,
        closed: bool = False,
        slug: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/events"
        params: Dict[str, Any] = {"limit": limit, "active": str(active).lower(), "closed": str(closed).lower()}
        if slug:
            params["slug"] = slug
        resp = self.session.get(url, params=params, timeout=self.timeout_s)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "events" in data:
            return data["events"]
        if isinstance(data, list):
            return data
        return []

    def get_event_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/events/slug/{slug}"
        resp = self.session.get(url, timeout=self.timeout_s)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if isinstance(data, dict) and data.get("slug"):
            return data
        return None

    def get_market_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/markets/slug/{slug}"
        resp = self.session.get(url, timeout=self.timeout_s)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if isinstance(data, dict) and data.get("slug"):
            return data
        return None

    def list_markets(
        self,
        limit: int = 200,
        offset: int = 0,
        active: bool = True,
        closed: bool = False,
        tag_id: Optional[int] = None,
        slug: Optional[str] = None,
        sports_market_types: Optional[List[str]] = None,
        end_date_min: Optional[str] = None,
        end_date_max: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/markets"
        params: Dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "active": str(active).lower(),
            "closed": str(closed).lower(),
        }
        if tag_id is not None:
            params["tag_id"] = tag_id
            params["related_tags"] = "true"
        if slug:
            params["slug"] = slug
        if sports_market_types:
            params["sports_market_types"] = sports_market_types
        if end_date_min:
            params["end_date_min"] = end_date_min
        if end_date_max:
            params["end_date_max"] = end_date_max

        resp = self.session.get(url, params=params, timeout=self.timeout_s)
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            # Retry without sports_market_types if the API rejects list params.
            if "sports_market_types" in params:
                params.pop("sports_market_types", None)
                resp = self.session.get(url, params=params, timeout=self.timeout_s)
                try:
                    resp.raise_for_status()
                except requests.HTTPError:
                    return []
            else:
                return []
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "markets" in data:
            return data["markets"]
        return []

    def list_sports(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/sports"
        resp = self.session.get(url, timeout=self.timeout_s)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return []


def _parse_json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            return []
    return []


def _infer_market_type(question: str, outcomes: List[str]) -> str:
    q = question.lower()
    outcome_set = set(o.lower() for o in outcomes)

    # Moneyline / 1X2
    if {"home", "draw", "away"}.issubset(outcome_set) or "moneyline" in q or "match result" in q:
        return "moneyline"

    # Both Teams To Score
    if "both teams to score" in q or "btts" in q or {"yes", "no"}.issubset(outcome_set) and "score" in q:
        return "btts"

    # Totals (Over/Under)
    if "over" in q and "under" in q and any(ch.isdigit() for ch in q):
        return "total"

    # Spread / Handicap
    if "spread" in q or "handicap" in q or "asian" in q:
        return "spread"

    return "other"


def _infer_market_type_from_market(market: Dict[str, Any], outcomes: List[str]) -> str:
    sports_type = str(market.get("sportsMarketType") or market.get("sports_market_type") or "").lower()
    if sports_type:
        if "spread" in sports_type:
            return "spread"
        if "total" in sports_type:
            return "total"
        if "btts" in sports_type or "both" in sports_type:
            return "btts"
        if "moneyline" in sports_type or "1x2" in sports_type:
            return "moneyline"
    question = str(market.get("question") or market.get("title") or "")
    return _infer_market_type(question, outcomes)


def _extract_start_time(event: Dict[str, Any]) -> Optional[str]:
    for key in ["startDateIso", "startDate", "endDateIso", "endDate", "start_time"]:
        if key in event and event[key]:
            return str(event[key])
    return None


def _iter_markets(event: Dict[str, Any], payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    if "markets" in event and isinstance(event["markets"], list):
        return event["markets"]
    if "markets" in payload and isinstance(payload["markets"], list):
        return payload["markets"]
    return []


def _is_soccer_event(event: Dict[str, Any]) -> bool:
    tag_fields = ["tags", "categories", "category", "sport"]
    text = " ".join(str(event.get(f, "")) for f in tag_fields).lower()
    return "soccer" in text or "football" in text


def _soccer_tag_ids(client: GammaClient) -> List[int]:
    tag_ids: List[int] = []
    for sport in client.list_sports():
        name = str(sport.get("name") or sport.get("sport") or "").lower()
        if "soccer" in name or "football" in name:
            tags = str(sport.get("tags") or sport.get("tagIds") or "")
            for part in tags.split(","):
                part = part.strip()
                if part.isdigit():
                    tag_ids.append(int(part))
    return tag_ids


def _fetch_related_markets_by_slug_prefix(
    client: GammaClient,
    slug_prefix: str,
    max_pages: int = 5,
    page_limit: int = 200,
    end_date_iso: Optional[str] = None,
) -> List[Dict[str, Any]]:
    markets: List[Dict[str, Any]] = []
    allowed_types = {"spreads", "totals", "both_teams_to_score", "moneyline"}
    end_min = None
    end_max = None
    if end_date_iso:
        if "T" in end_date_iso:
            end_min = end_date_iso
            end_max = end_date_iso
        else:
            end_min = f"{end_date_iso}T00:00:00Z"
            end_max = f"{end_date_iso}T23:59:59Z"
    try:
        direct = client.list_markets(
            limit=page_limit,
            offset=0,
            end_date_min=end_min,
            end_date_max=end_max,
        )
        for market in direct:
            slug = str(market.get("slug") or "")
            sports_type = str(market.get("sportsMarketType") or "").lower()
            if slug.startswith(slug_prefix) and (not sports_type or sports_type in allowed_types):
                markets.append(market)
    except Exception:
        pass

    tag_ids = _soccer_tag_ids(client)
    offsets = range(0, max_pages * page_limit, page_limit)

    for tag_id in tag_ids or [None]:
        for offset in offsets:
            batch = client.list_markets(
                limit=page_limit,
                offset=offset,
                tag_id=tag_id,
                end_date_min=end_min,
                end_date_max=end_max,
            )
            if not batch:
                break
            for market in batch:
                slug = str(market.get("slug") or "")
                sports_type = str(market.get("sportsMarketType") or "").lower()
                if slug.startswith(slug_prefix) and (not sports_type or sports_type in allowed_types):
                    markets.append(market)
        if markets:
            break

    # Last-resort: scan a few pages without tag filters.
    if not markets:
        for offset in offsets:
            batch = client.list_markets(
                limit=page_limit,
                offset=offset,
                end_date_min=end_min,
                end_date_max=end_max,
            )
            if not batch:
                break
            for market in batch:
                slug = str(market.get("slug") or "")
                sports_type = str(market.get("sportsMarketType") or "").lower()
                if slug.startswith(slug_prefix) and (not sports_type or sports_type in allowed_types):
                    markets.append(market)
    return markets


def _match_name_from_question(question: str) -> str:
    if ":" in question:
        return question.split(":", 1)[0].strip()
    if " vs " in question:
        return question.strip()
    return question.strip()


def _slug_variants(base_slug: str) -> List[str]:
    totals = ["1pt5", "2pt5", "3pt5", "4pt5"]
    spreads = ["1pt5", "2pt5"]
    variants = [
        base_slug,
        f"{base_slug}-btts",
    ]
    variants.extend([f"{base_slug}-total-{t}" for t in totals])
    variants.extend([f"{base_slug}-spread-away-{s}" for s in spreads])
    variants.extend([f"{base_slug}-spread-home-{s}" for s in spreads])
    return variants


def discover_soccer_markets(query: str, client: Optional[GammaClient] = None) -> Tuple[List[MarketMeta], List[EventRegistryEntry]]:
    client = client or GammaClient()
    payload = client.public_search(query)

    events: List[Dict[str, Any]] = []
    if isinstance(payload, dict):
        if "events" in payload:
            events = payload["events"]
        elif "data" in payload and isinstance(payload["data"], list):
            events = payload["data"]
    elif isinstance(payload, list):
        events = payload

    if not events:
        # If the query looks like a slug, try slug-specific endpoints first.
        if "-" in query and " " not in query:
            slug_event = client.get_event_by_slug(query)
            if slug_event:
                events = [slug_event]
            else:
                events = client.list_events(slug=query)
        if not events:
            events = client.list_events()

    market_meta: List[MarketMeta] = []
    registry_entries: List[EventRegistryEntry] = []

    registry = Registry(Path("data/registry.json"))
    registry.load()

    query_lower = query.lower()

    for event in events:
        if query_lower not in str(event).lower():
            if str(event.get("slug", "")).lower() != query_lower:
                continue
        if not _is_soccer_event(event):
            continue

        match_name = str(event.get("title") or event.get("name") or event.get("slug") or "soccer-match")
        start_time = _extract_start_time(event)
        event_id = registry.build_event_id(match_name, start_time)

        token_ids_by_type: Dict[str, List[str]] = {}
        market_ids_by_type: Dict[str, List[str]] = {}
        market_names_by_type: Dict[str, List[str]] = {}
        market_ids: List[str] = []

        markets_iter = list(_iter_markets(event, payload))
        # If we only got partial markets (often just moneyline), expand by slug prefix.
        slug_prefixes = set()
        if str(event.get("slug")):
            slug_prefixes.add(str(event.get("slug")))
        if "-" in query and " " not in query:
            slug_prefixes.add(query)
        end_date_iso = str(event.get("endDateIso") or event.get("endDate") or "")
        for slug_prefix in slug_prefixes:
            for slug in _slug_variants(slug_prefix):
                market = client.get_market_by_slug(slug)
                if market:
                    markets_iter.append(market)
            markets_iter.extend(
                _fetch_related_markets_by_slug_prefix(
                    client,
                    slug_prefix,
                    end_date_iso=end_date_iso,
                )
            )

        for market in markets_iter:
            market_id = str(market.get("id") or market.get("marketId") or "")
            if market_id:
                market_ids.append(market_id)

            outcomes = _parse_json_list(market.get("outcomes"))
            labels = [str(o) for o in outcomes]
            token_ids = _parse_json_list(market.get("clobTokenIds"))
            if not token_ids:
                token_ids = _parse_json_list(market.get("tokenIds"))

            market_type = _infer_market_type_from_market(market, labels)
            if token_ids:
                token_ids_by_type.setdefault(market_type, []).extend([str(t) for t in token_ids])
            if market_id:
                market_ids_by_type.setdefault(market_type, []).append(market_id)
            market_name = str(market.get("question") or market.get("title") or "")
            if market_name:
                market_names_by_type.setdefault(market_type, []).append(market_name)

            if market_id and labels and token_ids:
                market_meta.append(
                    MarketMeta(
                        market_id=market_id,
                        question=str(market.get("question") or market.get("title") or ""),
                        event_slug=str(event.get("slug")) if event.get("slug") else None,
                        event_name=match_name,
                        outcomes=[Outcome(label=label, token_id=str(token_id)) for label, token_id in zip(labels, token_ids)],
                        start_time=start_time,
                    )
                )

        entry = EventRegistryEntry(
            event_id=event_id,
            match_name=match_name,
            market_ids=sorted(set(market_ids)),
            token_ids_by_type={k: sorted(set(v)) for k, v in token_ids_by_type.items()},
            market_ids_by_type={k: sorted(set(v)) for k, v in market_ids_by_type.items()},
            market_names_by_type={k: sorted(set(v)) for k, v in market_names_by_type.items()},
            start_time=start_time,
        )
        registry.upsert(entry)
        registry_entries.append(entry)

    # Fallback: if no event matched but query looks like a slug, build from slug-prefix markets.
    if not registry_entries and "-" in query and " " not in query:
        slug_markets: List[Dict[str, Any]] = []
        for slug in _slug_variants(query):
            market = client.get_market_by_slug(slug)
            if market:
                slug_markets.append(market)
        if not slug_markets:
            slug_markets = _fetch_related_markets_by_slug_prefix(client, query)
        if slug_markets:
            sample = slug_markets[0]
            match_name = _match_name_from_question(str(sample.get("question") or sample.get("title") or query))
            start_time = _extract_start_time(sample)
            event_id = registry.build_event_id(match_name, start_time)

            token_ids_by_type: Dict[str, List[str]] = {}
            market_ids_by_type: Dict[str, List[str]] = {}
            market_names_by_type: Dict[str, List[str]] = {}
            market_ids: List[str] = []

            for market in slug_markets:
                market_id = str(market.get("id") or market.get("marketId") or "")
                if market_id:
                    market_ids.append(market_id)

                outcomes = _parse_json_list(market.get("outcomes"))
                labels = [str(o) for o in outcomes]
                token_ids = _parse_json_list(market.get("clobTokenIds"))
                if not token_ids:
                    token_ids = _parse_json_list(market.get("tokenIds"))

                market_type = _infer_market_type_from_market(market, labels)
                if token_ids:
                    token_ids_by_type.setdefault(market_type, []).extend([str(t) for t in token_ids])
                if market_id:
                    market_ids_by_type.setdefault(market_type, []).append(market_id)
                market_name = str(market.get("question") or market.get("title") or "")
                if market_name:
                    market_names_by_type.setdefault(market_type, []).append(market_name)

            entry = EventRegistryEntry(
                event_id=event_id,
                match_name=match_name,
                market_ids=sorted(set(market_ids)),
                token_ids_by_type={k: sorted(set(v)) for k, v in token_ids_by_type.items()},
                market_ids_by_type={k: sorted(set(v)) for k, v in market_ids_by_type.items()},
                market_names_by_type={k: sorted(set(v)) for k, v in market_names_by_type.items()},
                start_time=start_time,
            )
            registry.upsert(entry)
            registry_entries.append(entry)

    registry.save()
    return market_meta, registry_entries
