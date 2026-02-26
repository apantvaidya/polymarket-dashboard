"""Streamlit dashboard for Polymarket soccer markets."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
import streamlit as st
from sqlalchemy import create_engine, text

REGISTRY_PATH = Path("data/registry.json")
SNAPSHOT_DB = Path("data/snapshots.db")
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


def main() -> None:
    st.set_page_config(page_title="Market Edge Dashboard", layout="wide")
    st.title("Market Edge Dashboard")

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
    st.sidebar.write(f"Snapshots DB: `{SNAPSHOT_DB}`")

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

    if selected_market_names:
        st.write("**Market Names**")
        st.write(selected_market_names)

    st.markdown("### Live Market Metadata (Gamma)")
    markets = [fetch_market(market_id) for market_id in selected_market_ids]
    st.dataframe(market_table(markets), use_container_width=True)

    token_ids_by_type = entry.get("token_ids_by_type", {})
    token_ids = token_ids_by_type.get(selected_type, [])

    st.markdown("### Recent Snapshots (SQLite)")
    if token_ids:
        df = load_snapshots(token_ids, limit=200)
        if df.empty:
            st.info("No snapshots found. Run ingest with --snapshot-sqlite to populate.")
        else:
            st.dataframe(df, use_container_width=True)
            st.line_chart(df.sort_values("ts").set_index("ts")["mid"], height=250)
    else:
        st.info("No token_ids for this market type.")


if __name__ == "__main__":
    main()
