import json
from pathlib import Path

from market_edge.polymarket_gamma import _infer_market_type

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_infer_moneyline():
    data = load_json("sample_market_meta.json")
    market_type = _infer_market_type(data["question"], data["outcomes"])
    assert market_type == "moneyline"
