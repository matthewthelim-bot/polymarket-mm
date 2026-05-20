"""
Polymarket CLOB REST client.

Public endpoints (no auth):
    get_book(token_id) -> OrderBook
    get_market_token_ids(condition_id) -> tuple[str, str]  # (yes_token, no_token)

Authenticated endpoints (L2 HMAC auth):
    place_order(...)
    cancel_order(order_id)
    get_open_orders(market_id=None)
    get_positions()

Auth method: L2 (API key + HMAC-SHA256 of timestamp+method+path+body).
Credentials loaded via src.live.credentials.

SECURITY: Never log credential values or Authorization headers.
"""

from __future__ import annotations
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Optional

import requests
from datetime import datetime, timezone

from src.data.schemas import OrderBook, PriceLevel, Side
from src.live.credentials import Credentials


CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"


# ---------------------------------------------------------------------------
# Order dataclasses
# ---------------------------------------------------------------------------

@dataclass
class OrderRequest:
    """Input for placing a limit order."""
    token_id: str          # YES or NO token
    side: Side             # BUY or SELL
    price: float           # limit price (0–1)
    size: float            # number of contracts
    time_in_force: str = "GTC"   # GTC | IOC | FOK


@dataclass
class OrderResponse:
    """Result of a placed order."""
    order_id: str
    status: str            # matched | live | cancelled | etc.
    filled_size: float
    remaining_size: float


@dataclass
class OpenOrder:
    order_id: str
    token_id: str
    side: str
    price: float
    size: float
    filled_size: float


@dataclass
class Position:
    token_id: str
    size: float            # net contracts held


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class ClobClient:
    """
    Thin HTTP client for the Polymarket CLOB and Gamma APIs.

    Args:
        credentials: Loaded from src.live.credentials.load_credentials().
                     Pass None to use only unauthenticated endpoints.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        credentials: Optional[Credentials] = None,
        timeout: float = 10.0,
    ):
        self._creds = credentials
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers["Accept"] = "application/json"
        self._session.headers["Content-Type"] = "application/json"

    # ------------------------------------------------------------------
    # Public (no auth)
    # ------------------------------------------------------------------

    def get_book(self, token_id: str) -> OrderBook:
        """
        Fetch the current L2 order book for a token.

        Args:
            token_id: Polymarket YES or NO token ID.

        Returns:
            OrderBook with bids and asks sorted by price (bids desc, asks asc).
            The market_id field is set to the CLOB condition_id if available,
            otherwise falls back to token_id.

        Raises:
            requests.HTTPError: on non-2xx response.
        """
        resp = self._session.get(
            f"{CLOB_BASE}/book",
            params={"token_id": token_id},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        bids = sorted(
            [PriceLevel(price=float(b["price"]), size=float(b["size"]))
             for b in data.get("bids", [])],
            key=lambda l: -l.price,
        )
        asks = sorted(
            [PriceLevel(price=float(a["price"]), size=float(a["size"]))
             for a in data.get("asks", [])],
            key=lambda l: l.price,
        )

        # The CLOB book response includes "market" = condition_id
        condition_id = data.get("market", token_id)

        return OrderBook(
            market_id=condition_id,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(timezone.utc),
        )

    def get_condition_id_for_token(self, token_id: str) -> str:
        """
        Look up the condition_id for a given YES or NO token.

        Uses the /book endpoint which returns the condition_id in the `market` field.
        This is the cheapest way to map a token_id to its market condition_id.

        Args:
            token_id: YES or NO token ID.

        Returns:
            Condition ID string (0x…).

        Raises:
            requests.HTTPError: if the token doesn't exist or market is closed.
            ValueError: if the response doesn't contain a condition_id.
        """
        resp = self._session.get(
            f"{CLOB_BASE}/book",
            params={"token_id": token_id},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        condition_id = data.get("market")
        if not condition_id:
            raise ValueError(
                f"CLOB /book response for token {token_id[:20]}… "
                f"did not include 'market' field"
            )
        return condition_id

    def get_market_tokens(self, condition_id: str) -> tuple[str, str]:
        """
        Look up YES and NO token IDs for a market via the CLOB API.

        Args:
            condition_id: Hex condition ID (0x…).

        Returns:
            (yes_token_id, no_token_id) as strings.

        Raises:
            ValueError: if the market is not found or tokens are missing.
            requests.HTTPError: on non-2xx response.
        """
        resp = self._session.get(
            f"{CLOB_BASE}/markets/{condition_id}",
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        tokens = data.get("tokens", [])
        yes_token = next(
            (t["token_id"] for t in tokens
             if t.get("outcome", "").upper() in ("YES", "Y")),
            None,
        )
        no_token = next(
            (t["token_id"] for t in tokens
             if t.get("outcome", "").upper() in ("NO", "N")),
            None,
        )

        # Fallback: some markets use team names instead of YES/NO (sports markets).
        # In that case, just use position 0 = YES, position 1 = NO.
        if not yes_token and len(tokens) >= 1:
            yes_token = tokens[0].get("token_id")
        if not no_token and len(tokens) >= 2:
            no_token = tokens[1].get("token_id")

        if not yes_token or not no_token:
            raise ValueError(
                f"Market {condition_id} does not have both YES and NO tokens. "
                f"Tokens found: {[(t.get('outcome'), t.get('token_id', '')[:20]) for t in tokens]}"
            )

        return yes_token, no_token

    def get_market_token_ids(self, condition_id: str) -> tuple[str, str]:
        """
        Look up YES and NO token IDs for a market via the Gamma API.

        Args:
            condition_id: Hex condition ID (0x…).

        Returns:
            (yes_token_id, no_token_id) as strings.

        Raises:
            ValueError: if the condition ID is not found or has unexpected structure.
            requests.HTTPError: on non-2xx response.
        """
        resp = self._session.get(
            f"{GAMMA_BASE}/markets",
            params={"conditionId": condition_id},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        markets = data if isinstance(data, list) else data.get("markets", [])
        for mkt in markets:
            if mkt.get("conditionId", "").lower() == condition_id.lower():
                tokens = mkt.get("tokens", [])
                yes_token = next(
                    (t["token_id"] for t in tokens if t.get("outcome", "").upper() == "YES"),
                    None,
                )
                no_token = next(
                    (t["token_id"] for t in tokens if t.get("outcome", "").upper() == "NO"),
                    None,
                )
                if yes_token and no_token:
                    return yes_token, no_token
                raise ValueError(
                    f"Market {condition_id} found but missing YES/NO tokens: {tokens}"
                )

        raise ValueError(f"Condition ID {condition_id} not found in Gamma API response")

    # ------------------------------------------------------------------
    # Authenticated (L2 HMAC)
    # ------------------------------------------------------------------

    def place_order(self, order: OrderRequest) -> OrderResponse:
        """
        Place a limit order on the CLOB.

        Requires credentials.

        Args:
            order: OrderRequest with token_id, side, price, size.

        Returns:
            OrderResponse with order_id and fill status.
        """
        self._require_auth()
        payload = {
            "token_id": order.token_id,
            "side": order.side.value if hasattr(order.side, "value") else str(order.side),
            "price": str(round(order.price, 4)),
            "size": str(round(order.size, 2)),
            "time_in_force": order.time_in_force,
        }
        resp = self._authed_post("/order", payload)
        data = resp.json()
        return OrderResponse(
            order_id=data.get("order_id", ""),
            status=data.get("status", "unknown"),
            filled_size=float(data.get("size_matched", 0)),
            remaining_size=float(data.get("size_remaining", order.size)),
        )

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: The order ID returned by place_order.

        Returns:
            True if the cancellation was accepted.
        """
        self._require_auth()
        resp = self._authed_delete(f"/order/{order_id}")
        return resp.status_code in (200, 204)

    def get_open_orders(self, market_id: Optional[str] = None) -> list[OpenOrder]:
        """
        Fetch all open orders, optionally filtered by market.

        Args:
            market_id: token_id to filter by; None returns all markets.

        Returns:
            List of OpenOrder objects.
        """
        self._require_auth()
        params = {}
        if market_id:
            params["market"] = market_id
        resp = self._authed_get("/orders", params=params)
        data = resp.json()
        orders = data if isinstance(data, list) else data.get("data", [])
        return [
            OpenOrder(
                order_id=o.get("id", ""),
                token_id=o.get("asset_id", ""),
                side=o.get("side", ""),
                price=float(o.get("price", 0)),
                size=float(o.get("original_size", 0)),
                filled_size=float(o.get("size_matched", 0)),
            )
            for o in orders
        ]

    def get_positions(self) -> list[Position]:
        """
        Fetch current open positions.

        Returns:
            List of Position objects (token_id → net size).
        """
        self._require_auth()
        resp = self._authed_get("/positions")
        data = resp.json()
        positions = data if isinstance(data, list) else data.get("data", [])
        return [
            Position(
                token_id=p.get("asset", p.get("token_id", "")),
                size=float(p.get("size", p.get("quantity", 0))),
            )
            for p in positions
        ]

    # ------------------------------------------------------------------
    # Auth helpers (L2 HMAC)
    # ------------------------------------------------------------------

    def _require_auth(self) -> None:
        if self._creds is None:
            raise RuntimeError(
                "Authenticated endpoint called without credentials. "
                "Pass credentials to ClobClient()."
            )

    def _auth_headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        """
        Build L2 HMAC authentication headers.

        Header format:
            POLY-API-KEY: <api_key>
            POLY-TIMESTAMP: <unix_ms>
            POLY-SIGNATURE: HMAC-SHA256(secret, timestamp + method + path + body)
            POLY-PASSPHRASE: <passphrase>
        """
        ts = str(int(time.time() * 1000))
        message = ts + method.upper() + path + body
        sig = hmac.new(
            self._creds.poly_api_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()  # type: ignore[attr-defined]
        return {
            "POLY-API-KEY": self._creds.poly_api_key,
            "POLY-TIMESTAMP": ts,
            "POLY-SIGNATURE": sig,
            "POLY-PASSPHRASE": self._creds.poly_api_passphrase,
        }

    def _authed_get(self, path: str, params: Optional[dict] = None) -> requests.Response:
        headers = self._auth_headers("GET", path)
        resp = self._session.get(
            f"{CLOB_BASE}{path}",
            headers=headers,
            params=params,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp

    def _authed_post(self, path: str, payload: dict) -> requests.Response:
        body = json.dumps(payload)
        headers = self._auth_headers("POST", path, body)
        resp = self._session.post(
            f"{CLOB_BASE}{path}",
            headers=headers,
            data=body,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp

    def _authed_delete(self, path: str) -> requests.Response:
        headers = self._auth_headers("DELETE", path)
        resp = self._session.delete(
            f"{CLOB_BASE}{path}",
            headers=headers,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp
