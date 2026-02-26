from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Callable, Dict, Iterable, Optional

import websockets

from .polymarket_protocol import normalize_ws_message
from .utils import exponential_backoff, get_logger

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

EventCallback = Callable[[Any], None]


class WSClient:
    def __init__(
        self,
        token_ids: Iterable[str],
        event_id: Optional[str] = None,
        url: str = CLOB_WS_URL,
        debug: bool = False,
        max_runtime_seconds: Optional[int] = None,
    ) -> None:
        self.token_ids = list(token_ids)
        self.event_id = event_id
        self.url = url
        self.debug = debug
        self.max_runtime_seconds = max_runtime_seconds
        self.logger = get_logger("market_edge.ws", debug=debug)

    async def run(self, on_event: EventCallback) -> None:
        attempt = 0
        start = asyncio.get_event_loop().time()

        while True:
            if self.max_runtime_seconds is not None:
                elapsed = asyncio.get_event_loop().time() - start
                if elapsed >= self.max_runtime_seconds:
                    self.logger.info("Max runtime reached, stopping WS client.")
                    return

            session_id = str(uuid.uuid4())
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
                    await self._subscribe(ws)
                    self.logger.info("Connected and subscribed. Session %s", session_id)

                    async for message in ws:
                        try:
                            raw = json.loads(message)
                        except json.JSONDecodeError:
                            self.logger.warning("Received non-JSON message")
                            continue

                        if isinstance(raw, list):
                            for item in raw:
                                if not isinstance(item, dict):
                                    continue
                                events = normalize_ws_message(
                                    item,
                                    session_id=session_id,
                                    event_id=self.event_id,
                                    debug=self.debug,
                                )
                                for event in events:
                                    on_event(event)
                        elif isinstance(raw, dict):
                            events = normalize_ws_message(
                                raw,
                                session_id=session_id,
                                event_id=self.event_id,
                                debug=self.debug,
                            )
                            for event in events:
                                on_event(event)
                        else:
                            self.logger.warning("Unexpected message type: %s", type(raw).__name__)
            except Exception as exc:
                self.logger.warning("WS error: %s", exc)

            attempt += 1
            backoff = exponential_backoff(attempt)
            self.logger.info("Reconnecting in %.1fs", backoff)
            await asyncio.sleep(backoff)

    async def _subscribe(self, ws: websockets.WebSocketClientProtocol) -> None:
        payload: Dict[str, Any] = {
            "assets_ids": self.token_ids,
            "type": "market",
            "custom_feature_enabled": True,
        }
        await ws.send(json.dumps(payload))
