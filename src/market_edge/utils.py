from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict


SENSITIVE_KEYS = {"api_key", "secret", "signature", "private_key", "passphrase"}


def now_ms() -> int:
    return int(time.time() * 1000)


def exponential_backoff(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    sleep = base * (2 ** max(attempt, 0))
    return min(sleep, cap)


def sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = {}
    for key, value in payload.items():
        if key.lower() in SENSITIVE_KEYS:
            cleaned[key] = "***"
        else:
            cleaned[key] = value
    return cleaned


def safe_json_dumps(payload: Dict[str, Any]) -> str:
    return json.dumps(sanitize_payload(payload), ensure_ascii=True)


def get_logger(name: str, debug: bool = False) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    return logger
