"""Streamlit dashboard for Polymarket soccer markets."""
from __future__ import annotations

import json
import re
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pandas as pd
import requests
import streamlit as st
from sqlalchemy import create_engine, text

try:
    from market_edge.poisson_fair import fair_markets_from_probs, fair_price_map_from_probs
except ImportError:
    import importlib

    import market_edge.poisson_fair as _poisson_fair

    importlib.reload(_poisson_fair)
    fair_price_map_from_probs = _poisson_fair.fair_price_map_from_probs
    fair_markets_from_probs = _poisson_fair.fair_markets_from_probs
REGISTRY_PATH = Path("data/registry.json")
SNAPSHOT_DB = Path("data/snapshots.db")
ODDS_JSONL = Path("data/odds.jsonl")
GAMMA_BASE = "https://gamma-api.polymarket.com"


@st.cache_data(ttl=60)
def load_registry() -> Dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {}
    return json.loads(REGISTRY_PATH.read_text())


@st.cache_data(ttl=60)
def fetch_market(market_id: str) -> Optional[Dict[str, Any]]:
    url = f"{GAMMA_BASE}/markets/{market_id}"
    resp = requests.get(url, timeout=10)
    if resp.status_code != 200:
        return None
    return resp.json()


def load_snapshots(token_ids: List[str], limit: int = 200) -> pd.DataFrame:
    if not SNAPSHOT_DB.exists():
        return pd.DataFrame()
    engine = create_engine(f"sqlite:///{SNAPSHOT_DB}")
    placeholders = ",".join([":t" + str(i) for i in range(len(token_ids))])
    sql = text(
        f"""
        SELECT ts, event_id, token_id, best_bid, best_ask, mid, spread
        FROM snapshots
        WHERE token_id IN ({placeholders})
        ORDER BY ts DESC
        LIMIT :limit
        """
    )
    params = {f"t{i}": token_ids[i] for i in range(len(token_ids))}
    params["limit"] = limit
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)
    return df


def market_table(markets: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for m in markets:
        if not m:
            continue
        rows.append(
            {
                "id": m.get("id"),
                "slug": m.get("slug"),
                "question": m.get("question"),
                "sportsMarketType": m.get("sportsMarketType"),
                "line": m.get("line"),
                "liquidity": m.get("liquidity"),
                "liquidityClob": m.get("liquidityClob"),
                "volume": m.get("volume"),
                "volumeClob": m.get("volumeClob"),
                "competitive": m.get("competitive"),
                "bestBid": m.get("bestBid"),
                "bestAsk": m.get("bestAsk"),
                "lastTradePrice": m.get("lastTradePrice"),
                "spread": m.get("spread"),
                "startDateIso": m.get("startDateIso"),
                "endDateIso": m.get("endDateIso"),
            }
        )
    return pd.DataFrame(rows)


def _normalize_name(name: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in name).split())


def _simplify_team(name: str) -> str:
    tokens = _normalize_name(name).split()
    drop = {"fc", "afc", "cf", "sc", "the", "club", "de", "ac", "cfc"}
    return " ".join(t for t in tokens if t not in drop)


def _extract_line(text: str) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"(-?\\d+\\.\\d+|-?\\d+)", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _split_match_name(match_name: str) -> Optional[Tuple[str, str]]:
    lower = match_name.lower()
    for sep in (" vs ", " vs. ", " v ", " v. "):
        if sep in lower:
            left, right = match_name.split(sep, 1)
            return left.strip(), right.strip()
    return None


def _format_point(point: Optional[float]) -> Optional[str]:
    if point is None:
        return None
    try:
        return f"{float(point):g}"
    except (TypeError, ValueError):
        return None


def _match_tokens_for_odds(
    token_df: pd.DataFrame,
    odds_row: pd.Series,
    home_norm: Optional[str],
    away_norm: Optional[str],
    home_simple: Optional[str],
    away_simple: Optional[str],
) -> pd.DataFrame:
    name_norm = str(odds_row.get("name_norm") or "")
    point = odds_row.get("point")
    point_str = _format_point(point)

    exact = token_df[token_df["outcome_norm"] == name_norm]
    if not exact.empty:
        return exact

    market_type = odds_row.get("market_type")
    if market_type == "moneyline":
        if name_norm in {"draw", "tie"}:
            return token_df[token_df["outcome_norm"].isin(["draw", "tie", "x"])]
        if home_norm and name_norm == home_norm:
            team = token_df[token_df["outcome_norm"].str.contains(home_norm, na=False)]
            if not team.empty:
                return team
            return token_df[token_df["outcome_norm"].isin(["home"])]
        if away_norm and name_norm == away_norm:
            team = token_df[token_df["outcome_norm"].str.contains(away_norm, na=False)]
            if not team.empty:
                return team
            return token_df[token_df["outcome_norm"].isin(["away"])]
        if home_simple and (name_norm == home_simple or name_norm in home_simple or home_simple in name_norm):
            return token_df[
                token_df["outcome_norm"].str.contains(home_simple, na=False)
                | token_df["outcome_norm"].isin(["home"])
            ]
        if away_simple and (name_norm == away_simple or name_norm in away_simple or away_simple in name_norm):
            return token_df[
                token_df["outcome_norm"].str.contains(away_simple, na=False)
                | token_df["outcome_norm"].isin(["away"])
            ]
        return token_df[token_df["outcome_norm"].str.contains(name_norm, na=False)]

    if market_type == "total" and point_str:
        if "over" in name_norm or "under" in name_norm:
            return token_df[
                token_df["outcome_norm"].str.contains("over" if "over" in name_norm else "under", na=False)
                & token_df["outcome_norm"].str.contains(point_str, na=False)
            ]
        return token_df[token_df["outcome_norm"].str.contains(point_str, na=False)]

    if market_type == "spread" and point_str:
        team_norm = None
        if home_norm and home_norm in name_norm:
            team_norm = home_norm
        elif away_norm and away_norm in name_norm:
            team_norm = away_norm
        elif home_simple and home_simple in name_norm:
            team_norm = home_simple
        elif away_simple and away_simple in name_norm:
            team_norm = away_simple
        else:
            team_norm = name_norm

        candidates = token_df[
            token_df["outcome_norm"].str.contains(team_norm, na=False)
            & token_df["outcome_norm"].str.contains(point_str, na=False)
        ]
        if not candidates.empty:
            return candidates
        # Fallback for "home"/"away" labels
        if home_norm and team_norm in {home_norm, home_simple}:
            return token_df[
                token_df["outcome_norm"].str.contains("home", na=False)
                & token_df["outcome_norm"].str.contains(point_str, na=False)
            ]
        if away_norm and team_norm in {away_norm, away_simple}:
            return token_df[
                token_df["outcome_norm"].str.contains("away", na=False)
                & token_df["outcome_norm"].str.contains(point_str, na=False)
            ]
        return candidates

    if market_type == "btts":
        return token_df[token_df["outcome_norm"].isin([name_norm])]

    return token_df[token_df["outcome_norm"].str.contains(name_norm, na=False)]


def _load_latest_snapshots(token_ids: List[str]) -> pd.DataFrame:
    if not SNAPSHOT_DB.exists() or not token_ids:
        return pd.DataFrame()
    engine = create_engine(f"sqlite:///{SNAPSHOT_DB}")
    placeholders = ",".join([":t" + str(i) for i in range(len(token_ids))])
    sql = text(
        f"""
        SELECT s.ts, s.event_id, s.token_id, s.best_bid, s.best_ask, s.mid, s.spread
        FROM snapshots s
        INNER JOIN (
            SELECT token_id, MAX(ts) AS max_ts
            FROM snapshots
            WHERE token_id IN ({placeholders})
            GROUP BY token_id
        ) latest
        ON s.token_id = latest.token_id AND s.ts = latest.max_ts
        ORDER BY s.ts DESC
        """
    )
    params = {f"t{i}": token_ids[i] for i in range(len(token_ids))}
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)
    return df


def _load_odds_jsonl(event_id: Optional[str] = None) -> pd.DataFrame:
    if not ODDS_JSONL.exists():
        return pd.DataFrame()
    rows = []
    for line in ODDS_JSONL.read_text().splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event_id and payload.get("event_id") != event_id:
            continue
        for outcome in payload.get("outcomes", []):
            rows.append(
                {
                    "ts_ms": payload.get("ts_ms"),
                    "market": payload.get("market"),
                    "bookmaker": payload.get("bookmaker"),
                    "name": outcome.get("name"),
                    "price": outcome.get("price"),
                    "point": outcome.get("point"),
                }
            )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.sort_values("ts_ms").dropna(subset=["name", "price"])
    return df


def _latest_odds_by_key(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df["name_norm"] = df["name"].map(_normalize_name)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["point"] = pd.to_numeric(df["point"], errors="coerce")
    df = df.dropna(subset=["price"])
    df = df.sort_values("ts_ms")
    df = df.groupby(["market", "name_norm", "point"], dropna=False).tail(1)
    df["implied_prob"] = 1.0 / df["price"]
    return df


def _market_type_for_odds(market_key: str) -> Optional[str]:
    key = str(market_key or "").lower()
    if key in {"h2h", "h2h_3_way"}:
        return "moneyline"
    if key == "spreads":
        return "spread"
    if key == "totals":
        return "total"
    if key == "btts":
        return "btts"
    return None


def _extract_tokens(markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for market in markets:
        if not market:
            continue
        # Preferred: outcome tokens with explicit labels and token ids.
        outcome_tokens = market.get("outcomeTokens") or market.get("tokens") or []
        if isinstance(outcome_tokens, str):
            try:
                outcome_tokens = json.loads(outcome_tokens)
            except json.JSONDecodeError:
                outcome_tokens = []
        if isinstance(outcome_tokens, list) and outcome_tokens and isinstance(outcome_tokens[0], dict):
            for ot in outcome_tokens:
                label = ot.get("outcome") or ot.get("name") or ot.get("label") or ot.get("title")
                token_id = ot.get("tokenId") or ot.get("token_id") or ot.get("id")
                price = ot.get("price") or ot.get("probability") or ot.get("impliedProb")
                best_bid = ot.get("bestBid") or ot.get("best_bid")
                best_ask = ot.get("bestAsk") or ot.get("best_ask")
                if label is None or token_id is None:
                    continue
                rows.append(
                    {
                        "market_id": market.get("id"),
                        "question": market.get("question"),
                        "token_id": str(token_id),
                        "outcome": str(label),
                        "price": price,
                        "best_bid": best_bid,
                        "best_ask": best_ask,
                    }
                )
            continue

        outcomes = market.get("outcomes") or market.get("outcome") or []
        outcome_prices = market.get("outcomePrices") or market.get("outcome_prices") or []
        token_ids = market.get("clobTokenIds") or market.get("tokenIds") or market.get("token_ids") or []
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except json.JSONDecodeError:
                outcomes = []
        if isinstance(outcome_prices, str):
            try:
                outcome_prices = json.loads(outcome_prices)
            except json.JSONDecodeError:
                outcome_prices = []
        if isinstance(token_ids, str):
            try:
                token_ids = json.loads(token_ids)
            except json.JSONDecodeError:
                token_ids = []

        if len(outcomes) != len(token_ids):
            yes_token = market.get("yesTokenId") or market.get("yes_token_id")
            no_token = market.get("noTokenId") or market.get("no_token_id")
            if yes_token or no_token:
                labels = ["Yes", "No"]
                tokens = [yes_token, no_token]
                for label, token_id in zip(labels, tokens):
                    if token_id is None:
                        continue
                    price = None
                    best_bid = market.get("bestBid") or market.get("best_bid")
                    best_ask = market.get("bestAsk") or market.get("best_ask")
                    if isinstance(outcome_prices, list) and len(outcome_prices) == 2:
                        price = outcome_prices[labels.index(label)]
                    rows.append(
                        {
                            "market_id": market.get("id"),
                            "question": market.get("question"),
                            "token_id": str(token_id),
                            "outcome": str(label),
                            "price": price,
                            "best_bid": best_bid,
                            "best_ask": best_ask,
                        }
                    )
                continue

        for idx, (label, token_id) in enumerate(zip(outcomes, token_ids)):
            if isinstance(label, dict):
                label = label.get("name") or label.get("label") or label.get("title") or label.get("outcome")
            if label is None or token_id is None:
                continue
            price = None
            best_bid = market.get("bestBid") or market.get("best_bid")
            best_ask = market.get("bestAsk") or market.get("best_ask")
            if isinstance(outcome_prices, list) and idx < len(outcome_prices):
                price = outcome_prices[idx]
            rows.append(
                {
                    "market_id": market.get("id"),
                    "question": market.get("question"),
                    "token_id": str(token_id),
                    "outcome": str(label),
                    "price": price,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                }
            )
    return rows


def _find_total_odds(
    odds_latest: pd.DataFrame,
    line: float,
) -> Optional[Tuple[float, float]]:
    totals = odds_latest[odds_latest["market"] == "totals"].copy()
    if totals.empty:
        return None
    totals["name_norm"] = totals["name"].map(_normalize_name)
    totals["point"] = pd.to_numeric(totals["point"], errors="coerce")
    totals = totals[totals["point"] == line]
    if totals.empty:
        return None
    over = totals[totals["name_norm"].str.contains("over", na=False)]
    under = totals[totals["name_norm"].str.contains("under", na=False)]
    if over.empty or under.empty:
        return None
    over_prob = float(over.iloc[-1]["implied_prob"])
    under_prob = float(under.iloc[-1]["implied_prob"])
    return over_prob, under_prob


def _find_spread_odds(
    odds_latest: pd.DataFrame,
    line: float,
    home_name: str,
    away_name: str,
) -> Optional[Tuple[float, float]]:
    spreads = odds_latest[odds_latest["market"] == "spreads"].copy()
    if spreads.empty:
        return None
    spreads["name_norm"] = spreads["name"].map(_normalize_name)
    spreads["point"] = pd.to_numeric(spreads["point"], errors="coerce")
    home_norm = _normalize_name(home_name)
    away_norm = _normalize_name(away_name)

    home = spreads[(spreads["name_norm"].str.contains(home_norm, na=False)) & (spreads["point"] == line)]
    away = spreads[(spreads["name_norm"].str.contains(away_norm, na=False)) & (spreads["point"] == -line)]
    if home.empty or away.empty:
        # Fallback: try simplified names
        home_simple = _simplify_team(home_name)
        away_simple = _simplify_team(away_name)
        home = spreads[(spreads["name_norm"].str.contains(home_simple, na=False)) & (spreads["point"] == line)]
        away = spreads[(spreads["name_norm"].str.contains(away_simple, na=False)) & (spreads["point"] == -line)]
    if home.empty or away.empty:
        return None
    home_prob = float(home.iloc[-1]["implied_prob"])
    away_prob = float(away.iloc[-1]["implied_prob"])
    return home_prob, away_prob


def main() -> None:
    st.set_page_config(page_title="Market Edge Dashboard", layout="wide")
    st.title("Market Edge Dashboard")
    st.caption("Polymarket market metadata + Pinnacle odds (no matching required).")

    registry = load_registry()
    events = registry.get("events", {})

    if not events:
        st.warning("Registry is empty. Run ingest first to populate data/registry.json.")
        return

    event_ids = sorted(events.keys())
    event_id = st.sidebar.selectbox("Event", event_ids)
    entry = events[event_id]

    st.sidebar.markdown("### Data Sources")
    st.sidebar.write(f"Registry: `{REGISTRY_PATH}`")
    st.sidebar.write(f"Odds JSONL: `{ODDS_JSONL}`")

    st.subheader(entry.get("match_name", event_id))

    market_ids_by_type = entry.get("market_ids_by_type", {})
    market_names_by_type = entry.get("market_names_by_type", {})

    st.markdown("### Market Groups")
    cols = st.columns(4)
    for idx, market_type in enumerate(sorted(market_ids_by_type.keys())):
        with cols[idx % 4]:
            st.metric(market_type, len(market_ids_by_type.get(market_type, [])))

    selected_type = st.selectbox("Market Type", sorted(market_ids_by_type.keys()))
    selected_market_ids = market_ids_by_type.get(selected_type, [])
    selected_market_names = market_names_by_type.get(selected_type, [])

    tabs = st.tabs(["Markets", "Odds", "Fair Probabilities", "Mispricings"])

    with tabs[0]:
        if selected_market_names:
            st.markdown("**Market Names**")
            st.write(selected_market_names)

        with st.expander("Live Market Metadata (Gamma)", expanded=False):
            markets = [fetch_market(market_id) for market_id in selected_market_ids]
            st.dataframe(market_table(markets), use_container_width=True)

    markets = [fetch_market(market_id) for market_id in selected_market_ids]

    token_ids_by_type = entry.get("token_ids_by_type", {})
    token_ids = token_ids_by_type.get(selected_type, [])

    # Recent snapshots section removed per request. We still use latest snapshots
    # internally for Polymarket odds in the comparison table.

    odds_df = _load_odds_jsonl()
    odds_latest_all = _latest_odds_by_key(odds_df)
    token_rows = _extract_tokens(markets)
    token_df = pd.DataFrame(token_rows)

    with tabs[1]:
        st.markdown("### Odds (Separate Views)")
        left, right = st.columns([1.05, 1.0], gap="large")
        with left:
            st.markdown("#### Polymarket (Gamma Outcomes)")
            if token_df.empty:
                st.info("No token outcomes found in Gamma market data for this market type.")
            else:
                pm_df = token_df[["question", "outcome", "price"]].copy()
                st.dataframe(pm_df, use_container_width=True, height=360)

        with right:
            st.markdown("#### Pinnacle (Odds API)")
            if odds_latest_all.empty:
                st.info("No Pinnacle odds found in data/odds.jsonl.")
            else:
                odds_latest_all["market_type"] = odds_latest_all["market"].map(_market_type_for_odds)
                odds_latest = odds_latest_all[odds_latest_all["market_type"] == selected_type]
                if odds_latest.empty:
                    available = (
                        odds_df.assign(market_type=odds_df["market"].map(_market_type_for_odds))
                        .dropna(subset=["market_type"])["market_type"]
                        .value_counts()
                    )
                    if not available.empty:
                        st.info(
                            f"No Pinnacle odds for this market type. Available types: {', '.join(available.index)}."
                        )
                    else:
                        st.info("No Pinnacle odds for this market type.")
                else:
                    odds_view = odds_latest[["market", "name", "price", "implied_prob"]].copy()
                    if selected_type == "moneyline":
                        expanded = []
                        for _, row in odds_view.iterrows():
                            expanded.append(row.to_dict())
                            no_row = row.to_dict()
                            no_row["market"] = f"{row['market']}(no)"
                            no_row["name"] = row["name"]
                            no_row["implied_prob"] = 1.0 - float(row["implied_prob"])
                            no_row["price"] = None
                            expanded.append(no_row)
                        odds_view = pd.DataFrame(expanded)
                    st.dataframe(odds_view, use_container_width=True, height=360)

    with tabs[2]:
        st.markdown("### Derived Fair Probabilities (Poisson Fit)")
        if selected_type != "total":
            st.info("Select the `total` market type to view derived fair probabilities.")
        elif odds_latest_all.empty:
            st.info("No Pinnacle odds found in data/odds.jsonl.")
        else:
            match_name = entry.get("match_name", "")
            parts = _split_match_name(match_name) if match_name else None
            if not parts:
                st.info("Cannot derive fair prices without a parsable match name (e.g., 'Team A vs Team B').")
            else:
                home_team, away_team = parts

                totals_odds = _find_total_odds(odds_latest_all, 2.75)
                spreads_odds = _find_spread_odds(odds_latest_all, -0.75, home_team, away_team)
                if not totals_odds or not spreads_odds:
                    st.info("Need Pinnacle totals 2.75 and handicap -0.75 to fit the Poisson model.")
                else:
                    over_prob, under_prob = totals_odds
                    home_prob, away_prob = spreads_odds

                    fair = fair_price_map_from_probs(
                        over_prob_raw=over_prob,
                        under_prob_raw=under_prob,
                        home_prob_raw=home_prob,
                        away_prob_raw=away_prob,
                        total_line=2.75,
                        handicap_line=-0.75,
                        derived_lines=(1.5, 2.5, 3.5, 4.5),
                    )

                    st.write(
                        f"Fitted lambdas: home={fair['lambda_home']:.3f}, away={fair['lambda_away']:.3f} "
                        f"(error={fair['error']:.6f})"
                    )
                    total_rows = []
                    for line, probs in fair["totals"].items():
                        total_rows.append(
                            {
                                "Line": line,
                                "Over (fair)": probs["over"],
                                "Under (fair)": probs["under"],
                            }
                        )
                    st.dataframe(pd.DataFrame(total_rows), use_container_width=True)

    with tabs[3]:
        st.markdown("### Mispricings (Pinnacle Anchored)")
        if odds_latest_all.empty:
            st.info("No Pinnacle odds found in data/odds.jsonl.")
        elif token_df.empty:
            st.info("No Polymarket outcomes found for this market type.")
        else:
            buffer = st.slider("Edge buffer", min_value=0.0, max_value=0.1, value=0.03, step=0.005)

            match_name = entry.get("match_name", "")
            parts = _split_match_name(match_name) if match_name else None
            if not parts:
                st.info("Cannot derive fair prices without a parsable match name (e.g., 'Team A vs Team B').")
            else:
                home_team, away_team = parts

                totals_odds = _find_total_odds(odds_latest_all, 2.75)
                spreads_odds = _find_spread_odds(odds_latest_all, -0.75, home_team, away_team)
                if not totals_odds or not spreads_odds:
                    st.info("Need Pinnacle totals 2.75 and handicap -0.75 to fit the Poisson model.")
                else:
                    over_prob, under_prob = totals_odds
                    home_prob, away_prob = spreads_odds
                    fair = fair_markets_from_probs(
                        over_prob_raw=over_prob,
                        under_prob_raw=under_prob,
                        home_prob_raw=home_prob,
                        away_prob_raw=away_prob,
                        total_line=2.75,
                        handicap_line=-0.75,
                    )

                    st.write(
                        f"Fitted lambdas: home={fair['lambda_home']:.3f}, away={fair['lambda_away']:.3f} "
                        f"(error={fair['error']:.6f})"
                    )

                    market_meta = {str(m.get("id")): m for m in markets if m}
                    rows = []
                    for _, row in token_df.iterrows():
                        outcome = str(row.get("outcome") or "")
                        question = str(row.get("question") or "")
                        market_id = str(row.get("market_id") or "")
                        best_bid = row.get("best_bid")
                        best_ask = row.get("best_ask")
                        line = None
                        if market_id in market_meta:
                            line = market_meta[market_id].get("line")
                        if line is None:
                            line = _extract_line(question)

                        p_fair = None
                        outcome_norm = _normalize_name(outcome)

                        if selected_type == "moneyline":
                            if "draw" in outcome_norm or outcome_norm in {"tie"}:
                                p_fair = fair["moneyline"]["draw"]
                            else:
                                home_norm = _normalize_name(home_team)
                                away_norm = _normalize_name(away_team)
                                home_simple = _simplify_team(home_team)
                                away_simple = _simplify_team(away_team)
                                if outcome_norm in {home_norm, home_simple} or home_norm in outcome_norm:
                                    p_fair = fair["moneyline"]["home"]
                                elif outcome_norm in {away_norm, away_simple} or away_norm in outcome_norm:
                                    p_fair = fair["moneyline"]["away"]
                        elif selected_type == "total" and line is not None:
                            totals = fair["totals"].get(float(line))
                            if totals:
                                if "over" in outcome_norm:
                                    p_fair = totals["over"]
                                elif "under" in outcome_norm:
                                    p_fair = totals["under"]
                        elif selected_type == "spread" and line is not None:
                            spreads = fair["spreads"].get(float(line))
                            if spreads:
                                home_norm = _normalize_name(home_team)
                                away_norm = _normalize_name(away_team)
                                if home_norm in outcome_norm or _simplify_team(home_team) in outcome_norm:
                                    p_fair = spreads["home"]
                                elif away_norm in outcome_norm or _simplify_team(away_team) in outcome_norm:
                                    p_fair = spreads["away"]
                        elif selected_type == "btts":
                            if "yes" in outcome_norm:
                                p_fair = fair["btts"]["yes"]
                            elif "no" in outcome_norm:
                                p_fair = fair["btts"]["no"]

                        if p_fair is None:
                            continue

                        edge_buy = None
                        edge_sell = None
                        actionable_buy = False
                        actionable_sell = False
                        if best_ask is not None:
                            edge_buy = p_fair - float(best_ask)
                            actionable_buy = edge_buy >= buffer
                        if best_bid is not None:
                            edge_sell = float(best_bid) - p_fair
                            actionable_sell = edge_sell >= buffer

                        rows.append(
                            {
                                "Question": question,
                                "Outcome": outcome,
                                "Line": line,
                                "Fair Prob": p_fair,
                                "Best Ask": best_ask,
                                "Best Bid": best_bid,
                                "Edge Buy": edge_buy,
                                "Edge Sell": edge_sell,
                                "Buy?": actionable_buy,
                                "Sell?": actionable_sell,
                            }
                        )

                    if not rows:
                        st.info("No outcomes could be mapped for mispricing evaluation.")
                    else:
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, height=420)


if __name__ == "__main__":
    main()
