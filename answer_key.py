"""
Reference solution for client_skeleton.py. Attempt the exercises yourself
first - run this afterward to compare your approach, or to sanity-check the
server itself.

Run: python answer_key.py   (server must already be running)
"""
import csv
import hashlib
import json
import random
import time

import requests

BASE_URL = "http://127.0.0.1:8000"
MAX_ATTEMPTS = 6


def backoff_delay(attempt: int, base: float = 0.5, cap: float = 10.0) -> float:
    delay = min(cap, base * (2 ** attempt))
    return delay * (0.7 + 0.6 * random.random())  # +/-30% jitter


def _get_with_retry(url, params=None):
    """GET with 429/500/malformed-JSON handling. Returns parsed JSON dict or None if exhausted."""
    for attempt in range(MAX_ATTEMPTS):
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 2))
            time.sleep(wait)
            continue
        if resp.status_code == 500:
            time.sleep(backoff_delay(attempt))
            continue
        if resp.status_code == 410:
            return {"__cursor_expired__": True}
        try:
            return resp.json()
        except json.JSONDecodeError:
            time.sleep(backoff_delay(attempt))
            continue
    raise RuntimeError(f"Exhausted {MAX_ATTEMPTS} attempts against {url}")


def fetch_all_offset(page_size: int = 50) -> list[dict]:
    seen_ids = set()
    results = []
    page = 1
    while True:
        body = _get_with_retry(f"{BASE_URL}/orders", {"page": page, "page_size": page_size})
        data = body.get("data", [])
        if not data and page > body.get("total_pages", page):
            break
        for row in data:
            if row["order_id"] not in seen_ids:
                seen_ids.add(row["order_id"])
                results.append(row)
        if page >= body.get("total_pages", 0):
            break
        page += 1
    return results


def fetch_all_cursor(limit: int = 50) -> list[dict]:
    seen_ids = set()
    results = []
    cursor = None
    last_good_cursor = None
    while True:
        body = _get_with_retry(f"{BASE_URL}/orders/cursor", {"cursor": cursor, "limit": limit} if cursor else {"limit": limit})
        if body.get("__cursor_expired__"):
            # Resume from the last cursor we know was accepted, not the stale one.
            cursor = last_good_cursor
            continue
        for row in body.get("data", []):
            if row["order_id"] not in seen_ids:
                seen_ids.add(row["order_id"])
                results.append(row)
        if not body.get("has_more"):
            break
        last_good_cursor = cursor
        cursor = body.get("next_cursor")
    return results


def fetch_all_offset_chunked_to_csv(csv_path: str, page_size: int = 50) -> int:
    seen_ids = set()
    written = 0
    page = 1
    fieldnames = None
    with open(csv_path, "w", newline="") as f:
        writer = None
        while True:
            body = _get_with_retry(f"{BASE_URL}/orders", {"page": page, "page_size": page_size})
            data = body.get("data", [])
            for row in data:
                if row["order_id"] in seen_ids:
                    continue
                seen_ids.add(row["order_id"])
                if writer is None:
                    fieldnames = list(row.keys())
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                writer.writerow(row)
                written += 1
            if page >= body.get("total_pages", 0):
                break
            page += 1
    return written


def reconcile_against_truth(fetched_orders: list[dict]) -> dict:
    truth = requests.get(f"{BASE_URL}/admin/truth").json()
    fetched_ids = [o["order_id"] for o in fetched_orders]
    fetched_id_set = set(fetched_ids)
    duplicates = len(fetched_ids) - len(fetched_id_set)
    checksum = hashlib.sha256(json.dumps(sorted(fetched_id_set)).encode()).hexdigest()
    fetched_sum = round(sum(o["total_amount"] for o in fetched_orders), 2)
    expected_ids = set(range(truth["min_id"], truth["max_id"] + 1))
    missing = sorted(expected_ids - fetched_id_set)
    return {
        "expected_total": truth["total_records"],
        "fetched_total": len(fetched_id_set),
        "duplicates_removed_check": duplicates,
        "checksum_match": checksum == truth["id_checksum_sha256"],
        "missing_ids": missing,
        "amount_sum_match": fetched_sum == truth["total_amount_sum"],
        "fetched_amount_sum": fetched_sum,
        "truth_amount_sum": truth["total_amount_sum"],
    }


if __name__ == "__main__":
    print("--- Offset pagination full fetch ---")
    t0 = time.time()
    offset_orders = fetch_all_offset()
    print(f"fetched {len(offset_orders)} rows in {time.time() - t0:.1f}s")
    print(reconcile_against_truth(offset_orders))

    print("\n--- Cursor pagination full fetch ---")
    t0 = time.time()
    cursor_orders = fetch_all_cursor()
    print(f"fetched {len(cursor_orders)} rows in {time.time() - t0:.1f}s")
    print(reconcile_against_truth(cursor_orders))

    print("\n--- Chunked write to CSV ---")
    t0 = time.time()
    n = fetch_all_offset_chunked_to_csv("orders_export.csv")
    print(f"wrote {n} rows to orders_export.csv in {time.time() - t0:.1f}s")
