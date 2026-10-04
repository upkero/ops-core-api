# ops-core-api

[![CI](https://github.com/upkero/ops-core-api/actions/workflows/ci.yml/badge.svg)](https://github.com/upkero/ops-core-api/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

*[Русская версия](README.ru.md)*

Central operations backend for a fictional multi-business: customers, bookable slots, bookings,
service pricing, and a knowledge base with semantic search over pgvector.

![The double-booking scenario in the live demo: the second request for the same slot gets a 409.](docs/demo.png)

*The double-booking scenario in the live demo: the second request for the same slot gets a 409.*

The operator is one company running three things under one roof — a restaurant, a wellness clinic
and a set of hireable meeting rooms. That is why a single `resource_type` covers `table`,
`treatment_room` and `meeting_room`, and why the same customer list serves a dinner reservation and
a course of massages. The five services in this portfolio are five faces of that one business, not
five unrelated demos.

It is the source of truth that four separate agent services (voice, RAG, sales, MCP) read from,
but it stands on its own — a plain HTTP API with no agent framework anywhere in it.


---

## What it does

| Capability | Detail |
|---|---|
| CRM | Customer lookup by id and case-insensitive name search |
| Bookings | Availability listing and booking creation under a guest name, with the "one party per slot" rule enforced in the service layer *and* by a database constraint |
| Pricing | Quote for a quantity of a service, with volume discounts applied by an interchangeable policy |
| Knowledge base | Documents are chunked and embedded on write; search embeds the query and finds the nearest chunks with pgvector's `<=>` operator |

## Architecture

Layered, with a strict inward dependency rule — outer layers depend on inner ones, never the
reverse. HTTP schemas stop at the router; everything below passes frozen dataclass contracts, so a
service never sees a `Request` and never sees SQLAlchemy.

```
┌─────────────────────────────────────────────────────┐
│                    api/v1  (HTTP)                   │
├─────────────────────────────────────────────────────┤
│                    services  (business logic)       │
├─────────────────────────────────────────────────────┤
│        repositories          llm  (clients)         │
├─────────────────────────────────────────────────────┤
│                    interfaces  (ABC)                │
├─────────────────────────────────────────────────────┤
│          contracts          models  (ORM)           │
├─────────────────────────────────────────────────────┤
│          core / exceptions / bootstrap              │
└─────────────────────────────────────────────────────┘
```

Design patterns, and where to read them:

| Pattern | Where | Why |
|---|---|---|
| **Repository** | `interfaces/repositories/`, `repositories/` | Services reach data through ports that return contracts, so they never touch SQL. The in-memory test fakes are the second implementation. |
| **Factory** | `llm/embedding_factory.py` | The one place a provider client is constructed. Adding a provider is a new class plus a branch — no service changes. |
| **Strategy** | `interfaces/pricing/discount_policy.py`, `services/pricing/discount_policies.py` | The discount rule is an injected object rather than an `if quantity > 5`, so a new promotion never edits `PricingService`. |
| **Adapter** | `llm/openai_compatible_embedding_client.py` | Wraps the OpenAI SDK behind our own `EmbeddingClient` port; provider types stop at that boundary. |

`EmbeddingClient` is deliberately a separate port from any text-generation client: embedding and
completion are different responsibilities with different failure modes, and this service only ever
needs the first one.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

That brings up Postgres with pgvector and the API on <http://localhost:8000>, applies migrations,
and loads demo data (6 customers, two weeks of slots that roll forward on every start, 5 priced
services, 5 knowledge documents).
Interactive docs: <http://localhost:8000/docs>.

The Postgres password comes only from `.env` (`POSTGRES_PASSWORD`; `docker compose` refuses to start
without it) and the port is published on `127.0.0.1` only. `.env.example` carries a placeholder, so
set your own before the database is reachable from anywhere but your machine.

**No API keys are needed.** `EMBEDDING_PROVIDER` defaults to `hashing`, a deterministic local
embedder, so semantic search works offline out of the box. See
[Embeddings](#embeddings) for switching to a real provider.

## API

Every endpoint under `/api/v1` requires the `X-API-Key` header (see [Security](#security)) — reads
included. Only the health probes and the schema endpoints answer without it.

| Method | Path | Auth |
|---|---|---|
| `GET` | `/health/live` | open |
| `GET` | `/health/ready` | open |
| `GET` | `/api/v1/customers?search=&limit=&offset=` | **key** |
| `GET` | `/api/v1/customers/{id}` | **key** |
| `POST` | `/api/v1/customers` | **key** |
| `GET` | `/api/v1/booking-slots?date=&resource_type=&limit=&offset=` | **key** |
| `POST` | `/api/v1/bookings` | **key** |
| `GET` | `/api/v1/bookings?guest_name=&date=&status=` | **key** |
| `DELETE` | `/api/v1/bookings/{id}` | **key** |
| `GET` | `/api/v1/pricing?service=&quantity=` | **key** |
| `GET` | `/api/v1/pricing/services` | **key** |
| `POST` | `/api/v1/documents` | **key** |
| `POST` | `/api/v1/documents/search` | **key** |

### Examples

```bash
SECURITY_API_KEY=$(grep '^SECURITY_API_KEY=' .env | cut -d'"' -f2)

# Is the process up (what the container HEALTHCHECK polls)
curl localhost:8000/health/live
# {"status":"ok"}

# Can it serve traffic — 503 when the database is unreachable
curl localhost:8000/health/ready
# {"status":"ok","database":"ok"}

# Find a customer
curl "localhost:8000/api/v1/customers?search=anna" -H "X-API-Key: $SECURITY_API_KEY"

# Free slots for a given day, one page at a time (slots exist from tomorrow on)
TOMORROW=$(date -d tomorrow +%F)   # macOS: date -v+1d +%F
curl "localhost:8000/api/v1/booking-slots?date=$TOMORROW&resource_type=treatment_room&limit=10&offset=0" \
  -H "X-API-Key: $SECURITY_API_KEY"

# Price six sessions — the volume discount is applied by the service layer
curl "localhost:8000/api/v1/pricing?service=Deep%20Tissue%20Massage&quantity=6" \
  -H "X-API-Key: $SECURITY_API_KEY"
# {"service_name":"Deep Tissue Massage","unit_price":"120.00","quantity":6,
#  "subtotal":"720.00","discount_percent":"10","discount_amount":"72.00","total":"648.00"}

# Register a CRM account (used by the sales flow, not needed to book a table)
curl -X POST localhost:8000/api/v1/customers \
  -H "X-API-Key: $SECURITY_API_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"Priya Raman","notes":"Called about a table on Friday."}'

# Book a slot (repeat the same call and it returns 409 slot_unavailable)
curl -X POST localhost:8000/api/v1/bookings \
  -H "X-API-Key: $SECURITY_API_KEY" -H 'Content-Type: application/json' \
  -d '{"guest_name":"Priya Raman","slot_id":"<uuid>","party_size":2}'

# The same booking, retried safely after a dropped connection
curl -X POST localhost:8000/api/v1/bookings \
  -H "X-API-Key: $SECURITY_API_KEY" -H 'Idempotency-Key: 6f1c8b0e-…' \
  -H 'Content-Type: application/json' \
  -d '{"guest_name":"Priya Raman","slot_id":"<uuid>","party_size":2}'

# Add a document — it is chunked and embedded on the way in
curl -X POST localhost:8000/api/v1/documents \
  -H "X-API-Key: $SECURITY_API_KEY" -H 'Content-Type: application/json' \
  -d '{"title":"Gift vouchers","content":"Vouchers are valid for twelve months."}'

# Semantic search
curl -X POST localhost:8000/api/v1/documents/search \
  -H "X-API-Key: $SECURITY_API_KEY" -H 'Content-Type: application/json' \
  -d '{"query":"how do I cancel my appointment","top_k":3}'
```

The last call returns the cancellation policy first:

```json
{
  "query": "how do I cancel my appointment",
  "matches": [
    {
      "document_title": "Cancellation and rescheduling policy",
      "chunk_index": 0,
      "chunk_text": "Appointments can be cancelled or rescheduled free of charge up to twenty-four hours before the scheduled start time. ...",
      "distance": 0.6498,
      "score": 0.3502
    }
  ]
}
```

### Liveness and readiness are two questions

`/health/live` answers "is this process running" and checks nothing else. `/health/ready` answers
"can it serve traffic", which here means the database responds, and returns `503` when it does not.

They are separate because the answers have different consequences. The container `HEALTHCHECK`
polls `/health/live`: a liveness probe that touches the database restarts a perfectly healthy
container every time Postgres blinks — a restart cannot fix a database, and the restart loop makes
the outage worse. The four agent services poll `/health/ready` and treat exactly `200` as ready, so
they degrade gracefully instead of calling an API that cannot answer.

### Pagination

Every list endpoint returns the same envelope and takes the same `limit` / `offset` query
parameters (`limit` defaults to 20, capped at 200):

```json
{
  "items": [ … ],
  "total": 56,
  "limit": 20,
  "offset": 0,
  "has_more": true
}
```

`total` is what makes a truncated result honest — without it a caller cannot tell "these are all
the free slots" from "these are the first 20 of 56", which is how an agent ends up telling a
customer there is nothing available. It is counted over the *same* filters that produced `items`,
so `?resource_type=meeting_room` reports how many meeting rooms are free, not how many slots exist
in total. `has_more` is derived from the other three; it is there because an LLM consumer follows a
boolean far more reliably than it does arithmetic.

One implementation serves every collection: `PaginationParams` and `PageDTO` in
`contracts/pagination.py`, the `paginate()` helper in `repositories/pagination.py` that counts and
slices whatever `select()` a repository hands it, and the generic `Page[T]` response schema. A
repository adds paging by passing its query to the helper — there is no per-endpoint paging code.

`POST /documents/search` is deliberately *not* paginated: it takes `top_k` because relevance
ranking is not a collection you walk, and the second page of a vector search is rarely useful.

### Bookings carry a name, not an account

`POST /bookings` takes a `guest_name` and a slot. It does **not** reference a customer, and there
is no foreign key between the two.

That is a deliberate domain split rather than a shortcut. `Customer` models a CRM account with a
lifecycle — `lead`, `active`, `churned` — which the sales and MCP flows need. A table reserved by
phone has no account behind it: the restaurant needs a name for the evening and nothing more.
Forcing every reservation through find-or-create would invent accounts nobody asked for, and would
put a lookup in the middle of a live call.

Keeping the name on the booking also records what was actually said. If a customer is later renamed,
past bookings keep the name the table was reserved under; reading it through a foreign key would
rewrite history.

### Cancelling a booking

`DELETE /api/v1/bookings/{id}` cancels a reservation and puts the slot back on offer. The row is
kept with `status: cancelled` and a `cancelled_at` rather than deleted — the cancellation is itself
a fact the business needs, since the published policy charges half price for cancelling inside
twenty-four hours and counts no-shows separately.

`DELETE` rather than `POST /cancel` because HTTP defines it as idempotent, which is exactly what a
dropped call needs: cancelling twice returns the same booking and the same `200`.

Finding the booking to cancel is the other half — nobody reads a UUID down the phone — so
`GET /api/v1/bookings` filters by `guest_name`, `date` and `status` (defaulting to active ones).
**It requires the API key even when reads are public:** browsing free slots and prices is harmless,
but a list of guest names with the times they are expected is the most sensitive read in the API.

One consequence worth naming: `slot_id` cannot carry a plain `UNIQUE` constraint any more, because a
slot may be booked, cancelled and booked again. Uniqueness is a *partial* index —
`UNIQUE (slot_id) WHERE status = 'active'` — so the no-double-booking guarantee survives while the
history stays.

### Slots in the past

A slot that has already started is neither listed by `GET /booking-slots` nor bookable: `POST
/bookings` answers `409 slot_in_past`. `slot_date` and `slot_time` have no zone — they are the
wall clock of the business — so "already started" is judged against the current time in
`BUSINESS_TIMEZONE` (default `Europe/Moscow`).

### Retrying a booking

`POST /bookings` accepts an optional `Idempotency-Key` header. Repeat a request with the same key
and you get back the booking that key already created, with the same `201`, instead of being told
the slot is taken.

This exists because the caller that needs it most is a voice agent: a phone call drops mid-request
often enough to be the normal path, and without the key a retry is indistinguishable from someone
else having grabbed the slot — both are `409 slot_unavailable`. With it, the three outcomes stay
distinct:

| Situation | Response |
|---|---|
| Retry of your own request | `201` with the original booking |
| Someone else took the slot | `409 slot_unavailable` |
| Same key, different booking details | `409 idempotency_key_reused` |
| Same key, after that booking was cancelled | `409 idempotency_key_consumed` |

The key is stored on the booking row under a unique index, so two retries arriving at the same
instant cannot both insert — the database refuses the second rather than the application hoping to
notice in time.

A key is spent once and stays spent. Booking, cancelling and booking again inside one call needs a
fresh key for the second booking: replaying the old one would return the cancelled booking with a
`201`, telling the caller the table is reserved while the slot sits free. That is the reason for
`idempotency_key_consumed` — the request is fine, it just needs a new key.

Every error uses one envelope, so a client has a single shape to handle:

```json
{ "detail": "Booking slot '...' is already taken.", "error_code": "slot_unavailable" }
```

Every `error_code` the API can emit is listed in [`docs/error-codes.json`](docs/error-codes.json),
generated from the exception classes by `python -m src.app.cli.export_error_codes`. It is committed
because the four consumers keep a copy as a test fixture; a test here fails when the file falls
behind the classes, so a renamed code cannot quietly reach an agent that maps it to a phrase.

> **Money is serialised as a string** (`"120.00"`), not a number. Prices are `Decimal` end to end;
> emitting floats would hand clients a value that cannot represent cents exactly.

## Security

- **API key** — every endpoint under `/api/v1` requires `X-API-Key`, compared with
  `secrets.compare_digest`. `/health/live` and `/health/ready` stay open for the container runtime
  and the four consumers, and `/docs` + `/openapi.json` stay open so Swagger UI can render. Swagger
  publishes the scheme, so **Authorize** in `/docs` works.
- One rule, declared once: the guard is a `Security()` dependency on the `/api/v1` router, so a new
  router cannot be added unprotected by accident, and FastAPI derives the OpenAPI padlock from the
  same object that enforces it — there is no hand-written schema to drift.
- **Rate limiting** — 60 requests/minute per IP per route (`/bookings/{id}` is one route, whatever the
  id), and 20/minute for the two endpoints
  that call the embedding provider. In-memory, so counters are per process; the container runs a
  single worker.
- **CORS** — origins from `CORS_ALLOWED_ORIGINS`, credentials disabled (the key travels in a
  header, never a cookie).

Middleware runs `CORS → request_id → rate_limit → routes`, so a rejection still comes back with
CORS headers and a request id instead of surfacing as an opaque browser error. The key check is not
in that chain: it is a `Security()` dependency on the router (`api/v1/dependencies/security.py`),
which is why it runs after the rate limit and appears in the OpenAPI schema for free.

### Why the key is on reads too

A credential a browser holds is not a secret: if a React bundle carries the key, it is visible in
DevTools and in the shipped JavaScript. CORS does not help either — it is enforced by the browser,
so `curl` ignores it completely. So there is no version of "open reads" that is both public and
safe once the data is real, and `notes: "Allergic to lavender oil"` next to a customer name is
personal data under GDPR.

One rule for everything is also simpler to reason about than a per-endpoint policy: there is no
list of exceptions to keep in sync, and nothing can be left open by accident.

For a browser front end, keep the key in the server environment and call this API from a Next.js
route handler or server component, so the browser talks only to your own origin. Never expose it
through a `NEXT_PUBLIC_*` variable — those are inlined into the client bundle at build time.

An IP allowlist is a fine additional layer for the server-to-server callers, but it does not replace
the key: the allowlist says *which machine*, the key says *which consumer*, and the key is rotated
by editing one variable instead of the infrastructure.

## Embeddings

`EMBEDDING_PROVIDER` selects the implementation behind the `EmbeddingClient` port:

| Value | Behaviour |
|---|---|
| `hashing` (default) | Deterministic local embeddings — hashed word and character n-gram features with light stemming, L2-normalised. No key, no network, reproducible tests. |
| `openai` | The OpenAI embeddings API. Requires `EMBEDDING_API_KEY`. |
| `openai_compatible` | Any OpenAI-compatible server (Ollama, vLLM, OpenRouter, …). Requires `EMBEDDING_BASE_URL`; document and query text are sent to that server. |
| `local` | sentence-transformers in this process (e.g. `BAAI/bge-m3`, 1024 dims). Needs `LOCAL_MODELS=true` as an image build arg; weights download on first start into the `hf_cache` volume. |

The hashing embedder matches on vocabulary, not meaning. It handles inflection ("cancel" finds
"cancelled") but not synonymy — a query for "help with my diet" will not find a passage about
"nutrition coaching". Switch to a real provider when that matters; nothing outside `llm/` changes.

`EMBEDDING_DIMENSIONS` must match the `vector(1024)` columns in the schema. A mismatch is rejected
at startup rather than surfacing as an opaque database error on first insert.

### Changing provider invalidates the index

Vectors produced by two different models occupy different spaces. Cosine distance between them is
still a computable number, so a provider switch does not fail — it quietly starts returning
irrelevant results with normal-looking scores. Both models having the same width means the
dimension check above does not catch it either.

Every chunk therefore records the model that embedded it (`provider:model`, e.g. `hashing:v1`), and
search filters on it in SQL, so mixing spaces is impossible by construction. Switch provider without
re-indexing and you get a loud error instead of silent nonsense:

```json
{
  "detail": "The knowledge base was indexed with hashing:v1, but the configured embedding model is
             openai:text-embedding-3-small. Vectors from different models are not comparable.
             Re-index the documents (python -m src.app.cli.seed --force) or restore the previous
             EMBEDDING_PROVIDER/EMBEDDING_MODEL settings.",
  "error_code": "embedding_model_mismatch"
}
```

The hashing embedder's fingerprint carries a version (`hashing:v1`) because changing its tokenizer or
stemmer changes the vector space just as much as swapping providers does.

**Upgrading an existing database.** Migration `0007` resized the vectors to 1024 and therefore dropped
every stored chunk. The documents stay, and on the next start the seed step re-embeds every document
that has no chunks, so `docker compose up --build` is enough; there is nothing to run by hand.

## Configuration

All settings come from the environment; see [`.env.example`](.env.example) for the annotated list.

`SECURITY_API_KEY` ships as the placeholder `change-me-min-16-chars`. The four agent services carry the same
literal in their own `.env.example`, so copying each one to `.env` produces a demo where all five
already agree; it is a shared secret, and rotating it means rotating it in all five at once.

| Variable | Default | Purpose |
|---|---|---|
| `DB_URL` | — | Postgres async URL |
| `SECURITY_API_KEY` | — | **Required.** Shared secret for every `/api/v1` endpoint |
| `EMBEDDING_PROVIDER` | `hashing` | Embedding implementation |
| `EMBEDDING_DIMENSIONS` | `1024` | Vector width; must match the schema |
| `RATE_LIMIT_PER_MINUTE` | `60` | Global per-IP, per-route limit |
| `EMBEDDING_RATE_LIMIT_PER_MINUTE` | `20` | Limit for embedding-backed endpoints |
| `SLOT_WINDOW_DAYS` | `14` | Days ahead (from tomorrow) that booking slots are kept on offer; topped up on every start |
| `BUSINESS_TIMEZONE` | `Europe/Moscow` | Zone the slots' wall-clock `slot_date`/`slot_time` are in |
| `CORS_ALLOWED_ORIGINS` | empty | Comma-separated browser origins; `.env.example` allows `localhost:3000` and `localhost:5173` |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | Structured logging |

## Development

```bash
uv sync                      # install
uv run ruff check .          # lint
uv run mypy src              # type check (strict)
uv run pytest                # tests
```

Tests split in two. Unit tests drive the services against in-memory fakes of every port — no
database, no network. Integration tests drive the real app through `httpx.AsyncClient` with only
the database boundary replaced, so routing, middleware, validation and error handling are the
production ones.

A third group needs a real Postgres, because the `<=>` query, the `SELECT ... FOR UPDATE` row lock
and the `ILIKE` escaping are SQL and cannot be proven against a fake. They skip unless `TEST_DB_URL`
is set; CI supplies a pgvector service container.

```bash
docker run -d --name pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=ops_core_test \
  -p 5433:5432 pgvector/pgvector:pg17
TEST_DB_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/ops_core_test uv run pytest
```

Coverage on `services/` — the business logic — is enforced at 60% in CI and currently sits at 99%.

Other commands:

```bash
uv run alembic upgrade head           # apply migrations
uv run alembic revision --autogenerate -m "message"
uv run python -m src.app.cli.seed     # seed demo data (idempotent; --force to reseed)
```

## Known limitations

- Rate-limit counters live in process memory, so they reset on restart and would need Redis behind
  more than one worker.
- Rate limits are keyed on the caller's IP. Behind one Docker network or proxy every consumer (the
  agent services, the site bridge) arrives from the same address and shares one allowance per route,
  including the 20/minute embedding budget. Limit each consumer on its own side.
- A single shared write key, not per-user auth — the right weight for a demo (reads need the key too, see above).
- Offset-based paging. Fine at this size; a cursor would be the answer for a large, rapidly
  changing collection, where an insert can shift rows between pages.

## License

[MIT](LICENSE).
