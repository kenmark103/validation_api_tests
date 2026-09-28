"""
Mock API layer for practicing: pagination (offset + cursor), rate limiting,
retries, and chunked reading/writing against a flaky JSON API.

Run:
    pip install -r requirements.txt
    uvicorn app:app --reload --port 8000

Endpoints:
    GET  /orders?page=1&page_size=50
    GET  /orders/cursor?cursor=<token>&limit=50
    GET  /orders/{order_id}
    GET  /admin/truth
    GET  /admin/config
    POST /admin/config   body: {"rate_limit_max": int, "rate_limit_window_sec": int,
                                 "error_500_rate": float, "slow_rate": float,
                                 "malformed_rate": float, "dup_rate": float,
                                 "skip_rate": float}

See README.md for exercises.
"""
import base64
import hashlib
import json
import random
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from data_generator import ORDERS, ORDERS_BY_ID

app = FastAPI(title="Mock Orders API")

# ---------------------------------------------------------------------------
# Runtime-configurable chaos settings (separate from the underlying dataset,
# which stays fixed/deterministic). Defaults are randomized once at startup
# within sane ranges, then can be overridden via /admin/config.
# ---------------------------------------------------------------------------
_rng = random.Random()
CONFIG = {
    "rate_limit_max": 20,              # requests allowed per window
    "rate_limit_window_sec": 10,       # window size in seconds
    "error_500_rate": round(_rng.uniform(0.03, 0.08), 3),
    "slow_rate": round(_rng.uniform(0.05, 0.12), 3),
    "slow_delay_sec": 2.5,
    "malformed_rate": round(_rng.uniform(0.02, 0.05), 3),
    "dup_rate": round(_rng.uniform(0.03, 0.07), 3),   # offset pagination only
    "skip_rate": round(_rng.uniform(0.02, 0.05), 3),  # offset pagination only
    "cursor_ttl_sec": 30,               # cursor tokens expire after this long
}

# per-client (by token query param, falling back to IP) sliding window log
_request_log = defaultdict(deque)


def _client_key(request: Request) -> str:
    token = request.query_params.get("client")
    return token or (request.client.host if request.client else "anon")


def _check_rate_limit(request: Request) -> Response | None:
    key = _client_key(request)
    now = time.time()
    window = CONFIG["rate_limit_window_sec"]
    log = _request_log[key]
    while log and now - log[0] > window:
        log.popleft()
    if len(log) >= CONFIG["rate_limit_max"]:
        retry_after = max(1, int(window - (now - log[0])))
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "detail": "Too many requests"},
            headers={"Retry-After": str(retry_after)},
        )
    log.append(now)
    return None


def _maybe_chaos(request: Request) -> Response | None:
    """Randomly inject 500s, slow responses, or malformed JSON."""
    r = _rng.random()
    if r < CONFIG["error_500_rate"]:
        return JSONResponse(status_code=500, content={"error": "internal_error"})
    r2 = _rng.random()
    if r2 < CONFIG["slow_rate"]:
        time.sleep(CONFIG["slow_delay_sec"])
    r3 = _rng.random()
    if r3 < CONFIG["malformed_rate"]:
        # Deliberately truncated/broken JSON body, valid 200 status.
        broken = '{"data": [ {"order_id": 1, "customer_id": '  # cut off on purpose
        return Response(content=broken, media_type="application/json", status_code=200)
    return None


def _encode_cursor(last_id: int) -> str:
    payload = f"{last_id}:{time.time()}"
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_cursor(cursor: str):
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        last_id_str, ts_str = raw.split(":")
        return int(last_id_str), float(ts_str)
    except Exception:
        return None, None


@app.get("/orders")
def list_orders(request: Request, page: int = 1, page_size: int = 50):
    rl = _check_rate_limit(request)
    if rl:
        return rl
    chaos = _maybe_chaos(request)
    if chaos:
        return chaos

    page_size = max(1, min(page_size, 200))
    start = (page - 1) * page_size
    end = start + page_size
    items = [dict(o) for o in ORDERS[start:end]]

    # Inject duplicates and skips to simulate live data drift during pagination.
    if items and _rng.random() < CONFIG["dup_rate"]:
        items.append(dict(items[-1]))
    if items and _rng.random() < CONFIG["skip_rate"]:
        items.pop(_rng.randrange(len(items)))

    total = len(ORDERS)
    return {
        "data": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
    }


@app.get("/orders/cursor")
def list_orders_cursor(request: Request, cursor: str = None, limit: int = 50):
    rl = _check_rate_limit(request)
    if rl:
        return rl
    chaos = _maybe_chaos(request)
    if chaos:
        return chaos

    limit = max(1, min(limit, 200))
    last_id = 0
    if cursor:
        last_id, ts = _decode_cursor(cursor)
        if last_id is None:
            return JSONResponse(status_code=400, content={"error": "invalid_cursor"})
        if time.time() - ts > CONFIG["cursor_ttl_sec"]:
            return JSONResponse(
                status_code=410,
                content={"error": "cursor_expired",
                         "detail": "Cursor is stale, restart pagination or request a fresh one"},
            )

    remaining = [o for o in ORDERS if o["order_id"] > last_id]
    page_items = [dict(o) for o in remaining[:limit]]
    next_cursor = _encode_cursor(page_items[-1]["order_id"]) if page_items else None

    return {
        "data": page_items,
        "next_cursor": next_cursor,
        "has_more": len(remaining) > limit,
    }


@app.get("/orders/{order_id}")
def get_order(order_id: int, request: Request):
    rl = _check_rate_limit(request)
    if rl:
        return rl
    order = ORDERS_BY_ID.get(order_id)
    if not order:
        return JSONResponse(status_code=404, content={"error": "not_found"})
    return order


@app.get("/admin/truth")
def admin_truth():
    """Ground truth for validating your reconciliation logic. Not rate-limited or flaky."""
    ids_sorted = sorted(ORDERS_BY_ID.keys())
    checksum = hashlib.sha256(json.dumps(ids_sorted).encode()).hexdigest()
    total_amount_sum = round(sum(o["total_amount"] for o in ORDERS), 2)
    return {
        "total_records": len(ORDERS),
        "id_checksum_sha256": checksum,
        "min_id": ids_sorted[0],
        "max_id": ids_sorted[-1],
        "total_amount_sum": total_amount_sum,
    }


@app.get("/admin/config")
def get_config():
    return CONFIG


@app.post("/admin/config")
def update_config(overrides: dict):
    CONFIG.update(overrides)
    return CONFIG
