import json
from pathlib import Path

from market_edge.polymarket_protocol import normalize_ws_message

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_normalize_snapshot_message():
    raw = {
        "type": "snapshot",
        "tokenId": "123",
        "marketId": "m1",
        "bids": load_json("sample_snapshot.json")["bids"],
        "asks": load_json("sample_snapshot.json")["asks"],
    }

    events = normalize_ws_message(raw, session_id="s1", event_id="e1", debug=True)
    event = events[0]
    assert event.event_type == "snapshot"
    assert event.token_id == "123"
    assert event.market_id == "m1"
    assert "book" in event.payload
    assert event.payload["book"]["bids"]
    assert event.raw is not None


def test_normalize_delta_message():
    raw = {
        "type": "delta",
        "tokenId": "123",
        "marketId": "m1",
        "data": {
            "bids": load_json("sample_deltas.json")[0]["bids"],
            "asks": [],
        },
    }

    events = normalize_ws_message(raw, session_id="s1", event_id="e1", debug=False)
    event = events[0]
    assert event.event_type == "delta"
    assert event.payload["book"]["bids"]
    assert event.raw is None
