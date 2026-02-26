import json
from pathlib import Path

import pytest
from market_edge.orderbook import OrderBook


FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_apply_snapshot_and_best_levels():
    ob = OrderBook()
    snapshot = load_json("sample_snapshot.json")
    ob.apply_snapshot(snapshot)

    assert ob.best_bid() == 0.45
    assert ob.best_ask() == 0.55
    assert ob.mid() == 0.5
    assert ob.spread() == pytest.approx(0.10)


def test_apply_deltas_and_deletions():
    ob = OrderBook()
    ob.apply_snapshot(load_json("sample_snapshot.json"))

    deltas = load_json("sample_deltas.json")
    for delta in deltas:
        ob.apply_delta(delta)

    assert ob.bids.get(0.45) == 120
    assert 0.55 not in ob.asks
    assert ob.best_ask() == 0.54


def test_top_n_levels():
    ob = OrderBook()
    ob.apply_snapshot(load_json("sample_snapshot.json"))

    bids = ob.top_n_bids(1)
    asks = ob.top_n_asks(2)

    assert bids == [[0.45, 100.0]]
    assert asks == [[0.55, 90.0], [0.56, 20.0]]
