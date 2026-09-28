# Mock Orders API — pagination / rate-limiting / flakiness practice

A local FastAPI server simulating a real third-party JSON API: paginated
(both offset and cursor style), rate-limited, and randomly flaky —
so you can practice the exact skills mentioned for the Wingubox assessment
(Python scripting + API/Postman-style validation), on top of the SQL/pandas
side you've already drilled.

## Setup

```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Leave that running in one terminal. In another terminal, work through
`client_skeleton.py`.

## Endpoints

- `GET /orders?page=1&page_size=50` — offset pagination. Max page_size 200.
- `GET /orders/cursor?cursor=<token>&limit=50` — cursor pagination. First
  call omits `cursor`. Response includes `next_cursor` and `has_more`.
  Cursors expire after ~30s (`410 cursor_expired`).
- `GET /orders/{id}` — single record.
- `GET /admin/truth` — ground truth (never rate-limited, never flaky). Use
  this to verify your reconciliation: `total_records`, `id_checksum_sha256`
  (sha256 of the sorted JSON list of all order_ids), `total_amount_sum`.
- `GET /admin/config` / `POST /admin/config` — view/override chaos settings
  (rate limit, error rates, etc). Useful once you've got the basics working
  and want to crank up the difficulty.

## Behavior to expect (this is the point of the exercise)

- **429 rate limited** — comes with a `Retry-After` header (seconds). Sleep
  that long, then retry.
- **500 internal_error** — random, transient. Retry with exponential
  backoff + jitter.
- **200 with truncated/broken JSON body** — your `resp.json()` call will
  raise `JSONDecodeError`. Catch it and retry the same request.
- **Duplicate records across pages** (offset pagination only) — the same
  `order_id` can show up in two consecutive pages. Dedupe by id.
- **Skipped records** (offset pagination only) — simulates a record being
  deleted/moved while you're mid-pagination. You will NOT get an error for
  this — you'll only notice by reconciling your final count/checksum
  against `/admin/truth`. This is deliberate: it's the failure mode that's
  easiest to miss in real life.
- Cursor pagination does not have the dup/skip injection — notice that it
  reconciles cleanly while offset pagination (on the same underlying data)
  sometimes doesn't. That's a real, interview-worthy distinction: offset
  pagination is vulnerable to drift on a live dataset; cursor pagination
  (keyed off a monotonic id) is more robust to it.

## Exercises (do these in `client_skeleton.py`, in order)

1. **`fetch_all_offset`** — pull every order via offset pagination, handling
   429/500/malformed JSON, deduping by id.
2. **`fetch_all_cursor`** — same via cursor pagination, additionally
   handling `410 cursor_expired` (think about what state you need to keep
   to resume correctly — retrying the *same* cursor won't work).
3. **`fetch_all_offset_chunked_to_csv`** — same as #1, but write each page
   straight to CSV as you go instead of holding everything in memory. This
   is the pattern for "large dataset that doesn't fit in memory."
4. **`reconcile_against_truth`** — compare what you fetched against
   `/admin/truth`: does the count match? the checksum? total_amount_sum?
   any ids missing? any duplicates that survived your dedupe?
5. **`backoff_delay`** — exponential backoff with jitter, used by all the
   above.

Once you've attempted all five yourself, run `python answer_key.py` to
compare against a reference implementation and see a live validation
report (it deliberately shows the offset-vs-cursor discrepancy described
above).

## Stretch goals (if you finish early)

- Parallelize the offset fetch across a few worker threads while still
  respecting the shared rate limit (the server's rate limiter is per
  `client` query param / IP — try running two workers with different
  `client=` values vs the same one and see what happens).
- Build an incremental sync: instead of re-fetching everything each run,
  track `updated_at` and only pull records changed since your last sync —
  then upsert into a local SQLite table (ties back into your SQL practice).
- Turn up the chaos via `POST /admin/config` (e.g. `error_500_rate: 0.3`)
  and see if your retry logic still holds up.
