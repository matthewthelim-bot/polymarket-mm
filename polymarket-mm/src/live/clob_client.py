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
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

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
    HTTP client for the Polymarket CLOB and Gamma APIs.

    Public endpoints (no auth): get_book, get_condition_id_for_token, get_market_tokens,
    get_market_token_ids.

    Authenticated endpoints: place_order, cancel_order, get_open_orders, get_positions.
    These delegate to py-clob-client for correct EIP-712 order signing and L2 HMAC auth.

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
        self._py_client = None  # lazy-initialized when auth is needed

    def _get_py_client(self):
        """
        Lazy-initialize the py-clob-client ClobClient for authenticated operations.
        Requires py-clob-client to be installed.
        """
        if self._py_client is not None:
            return self._py_client
        self._require_auth()
        try:
            from py_clob_client.client import ClobClient as _PyClobClient
            from py_clob_client.clob_types import ApiCreds
            from py_clob_client.constants import POLYGON
        except ImportError:
            raise RuntimeError(
                "py-clob-client is required for authenticated operations. "
                "Install it: pip install py-clob-client"
            )
        api_creds = ApiCreds(
            api_key=self._creds.poly_api_key,
            api_secret=self._creds.poly_api_secret,
            api_passphrase=self._creds.poly_api_passphrase,
        )
        self._py_client = _PyClobClient(
            host=CLOB_BASE,
            chain_id=POLYGON,
            key=self._creds.private_key,
            creds=api_creds,
            signature_type=1,   # L2 auth
        )
        return self._py_client

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

        Requires credentials. Uses py-clob-client for correct EIP-712 signing.

        Args:
            order: OrderRequest with token_id, side, price, size, time_in_force.

        Returns:
            OrderResponse with order_id and fill status.
        """
        from py_clob_client.clob_types import OrderArgs, OrderType
        py_client = self._get_py_client()

        side_str = (order.side.value if hasattr(order.side, "value") else str(order.side)).upper()

        # Map time_in_force to OrderType. Polymarket has no IOC; FAK
        # (fill-and-kill) is the equivalent — fill what's available, cancel
        # the rest. An unknown TIF must not silently rest on the book.
        order_type_map = {
            "GTC": OrderType.GTC,
            "GTD": OrderType.GTD,
            "FOK": OrderType.FOK,
            "FAK": OrderType.FAK,
            "IOC": OrderType.FAK,
        }
        tif = order.time_in_force.upper()
        if tif not in order_type_map:
            raise ValueError(f"Unsupported time_in_force: {order.time_in_force}")
        order_type = order_type_map[tif]

        order_args = OrderArgs(
            token_id=order.token_id,
            price=order.price,
            size=order.size,
            side=side_str,
        )
        signed = py_client.create_order(order_args)
        resp = py_client.post_order(signed, order_type)

        if resp is None:
            raise RuntimeError("Order placement returned None from py-clob-client")

        return OrderResponse(
            order_id=resp.get("orderID", resp.get("order_id", "")),
            status=resp.get("status", "unknown"),
            filled_size=float(resp.get("size_matched", 0)),
            remaining_size=float(resp.get("size_remaining", order.size)),
        )

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.

        Args:
            order_id: The order ID returned by place_order.

        Returns:
            True if the cancellation was accepted.
        """
        py_client = self._get_py_client()
        resp = py_client.cancel(order_id=order_id)
        return resp is not None

    def get_open_orders(self, market_id: Optional[str] = None) -> list[OpenOrder]:
        """
        Fetch all open orders, optionally filtered by market.

        Args:
            market_id: token_id to filter by; None returns all markets.

        Returns:
            List of OpenOrder objects.
        """
        py_client = self._get_py_client()
        params = {}
        if market_id:
            params["market"] = market_id
        # py-clob-client get_orders returns raw list
        raw = py_client.get_orders()
        orders = raw if isinstance(raw, list) else []
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
        Fetch current open positions via CLOB balance-allowance endpoint.

        Returns:
            List of Position objects (token_id -> net size).
        """
        py_client = self._get_py_client()
        resp = py_client.get_balance_allowance()
        if resp is None:
            return []
        # Response is a dict; positions may be inside 'assets'
        assets = resp if isinstance(resp, list) else resp.get("assets", [])
        return [
            Position(
                token_id=p.get("asset_id", p.get("token_id", "")),
                size=float(p.get("balance", p.get("size", 0))),
            )
            for p in assets
            if float(p.get("balance", p.get("size", 0))) > 0
        ]

    # ------------------------------------------------------------------
    # Auth helper
    # ------------------------------------------------------------------

    def _require_auth(self) -> None:
        if self._creds is None:
            raise RuntimeError(
                "Authenticated endpoint called without credentials. "
                "Pass credentials to ClobClient()."
            )
