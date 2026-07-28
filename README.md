# ops-core-api

[![CI](https://github.com/upkero/ops-core-api/actions/workflows/ci.yml/badge.svg)](https://github.com/upkero/ops-core-api/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

Central operations backend for a fictional multi-business (restaurant + wellness clinic +
consulting): customers, bookable slots, bookings, service pricing, and a knowledge base with
semantic search over pgvector.

It is the source of truth that four separate agent services (voice, RAG, sales, MCP) read from,
but it stands on its own — a plain HTTP API with no agent framework anywhere in it.

*[Русская версия ниже](#ops-core-api-русская-версия).*

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
service never sees a `Request` and never sees SQLAlchemy. The full description is in
[`docs/architecture.md`](docs/architecture.md).

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
and loads demo data (6 customers, a week of slots, 5 priced services, 5 knowledge documents).
Interactive docs: <http://localhost:8000/docs>.

**No API keys are needed.** `EMBEDDING_PROVIDER` defaults to `hashing`, a deterministic local
embedder, so semantic search works offline out of the box. See
[Embeddings](#embeddings) for switching to a real provider.

## API

Every endpoint under `/api/v1` requires the `X-API-Key` header (see [Security](#security)). Only `/health` and the schema endpoints answer without it.

| Method | Path | Auth |
|---|---|---|
| `GET` | `/health` | open |
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
API_KEY=$(grep '^API_KEY=' .env | cut -d'"' -f2)

# Service and database status
curl localhost:8000/health
# {"status":"ok","database":"ok"}

# Find a customer
curl "localhost:8000/api/v1/customers?search=anna"

# Free slots for a given day, one page at a time
curl "localhost:8000/api/v1/booking-slots?date=2026-07-24&resource_type=table&limit=10&offset=0"

# Price six sessions — the volume discount is applied by the service layer
curl "localhost:8000/api/v1/pricing?service=Deep%20Tissue%20Massage&quantity=6"
# {"service_name":"Deep Tissue Massage","unit_price":"120.00","quantity":6,
#  "subtotal":"720.00","discount_percent":"10","discount_amount":"72.00","total":"648.00"}

# Register a CRM account (used by the sales flow, not needed to book a table)
curl -X POST localhost:8000/api/v1/customers \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"name":"Priya Raman","notes":"Called about a table on Friday."}'

# Book a slot (repeat the same call and it returns 409 slot_unavailable)
curl -X POST localhost:8000/api/v1/bookings \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"customer_id":"<uuid>","slot_id":"<uuid>","party_size":2}'

# The same booking, retried safely after a dropped connection
curl -X POST localhost:8000/api/v1/bookings \
  -H "X-API-Key: $API_KEY" -H 'Idempotency-Key: 6f1c8b0e-…' \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"<uuid>","slot_id":"<uuid>","party_size":2}'

# Add a document — it is chunked and embedded on the way in
curl -X POST localhost:8000/api/v1/documents \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
  -d '{"title":"Gift vouchers","content":"Vouchers are valid for twelve months."}'

# Semantic search
curl -X POST localhost:8000/api/v1/documents/search \
  -H 'Content-Type: application/json' \
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

> **Money is serialised as a string** (`"120.00"`), not a number. Prices are `Decimal` end to end;
> emitting floats would hand clients a value that cannot represent cents exactly.

## Security

- **API key** — every endpoint under `/api/v1` requires `X-API-Key`, compared with
  `secrets.compare_digest`. `/health` stays open for the container runtime, and `/docs` +
  `/openapi.json` stay open so Swagger UI can render. Swagger publishes the scheme, so **Authorize**
  in `/docs` works.
- One rule, declared once: the guard is a `Security()` dependency on the `/api/v1` router, so a new
  router cannot be added unprotected by accident, and FastAPI derives the OpenAPI padlock from the
  same object that enforces it — there is no hand-written schema to drift.
- **Rate limiting** — 60 requests/minute per IP per endpoint, and 20/minute for the two endpoints
  that call the embedding provider. In-memory, so counters are per process; the container runs a
  single worker.
- **CORS** — origins from `CORS_ALLOWED_ORIGINS`, credentials disabled (the key travels in a
  header, never a cookie).

Middleware runs `CORS → request_id → api_key → rate_limit`, so a rejection still comes back with
CORS headers and a request id instead of surfacing as an opaque browser error.

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
| `openai_compatible` | Any OpenAI-compatible server (Ollama, vLLM, …). Requires `EMBEDDING_BASE_URL`. |

The local embedder matches on vocabulary, not meaning. It handles inflection ("cancel" finds
"cancelled") but not synonymy — a query for "help with my diet" will not find a passage about
"nutrition coaching". Switch to a real provider when that matters; nothing outside `llm/` changes.

`EMBEDDING_DIMENSIONS` must match the `vector(1536)` columns in the schema. A mismatch is rejected
at startup rather than surfacing as an opaque database error on first insert.

### Changing provider invalidates the index

Vectors produced by two different models occupy different spaces. Cosine distance between them is
still a computable number, so a provider switch does not fail — it quietly starts returning
irrelevant results with normal-looking scores. Both models being 1536-dimensional means the
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

The local embedder's fingerprint carries a version (`hashing:v1`) because changing its tokenizer or
stemmer changes the vector space just as much as swapping providers does.

## Configuration

All settings come from the environment; see [`.env.example`](.env.example) for the annotated list.

`API_KEY` ships as the placeholder `change-me-min-16-chars`. The four agent services carry the same
literal in their own `.env.example`, so copying each one to `.env` produces a demo where all five
already agree; it is a shared secret, and rotating it means rotating it in all five at once.

| Variable | Default | Purpose |
|---|---|---|
| `DB_URL` | — | Postgres async URL |
| `API_KEY` | — | **Required.** Shared secret for every `/api/v1` endpoint |
| `EMBEDDING_PROVIDER` | `hashing` | Embedding implementation |
| `EMBEDDING_DIMENSIONS` | `1536` | Vector width; must match the schema |
| `RATE_LIMIT_PER_MINUTE` | `60` | Global per-IP, per-endpoint limit |
| `EMBEDDING_RATE_LIMIT_PER_MINUTE` | `20` | Limit for embedding-backed endpoints |
| `CORS_ALLOWED_ORIGINS` | `localhost:3000,localhost:5173` | Comma-separated browser origins |
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
- A single shared write key, not per-user auth — the right weight for a public read-only demo.
- Offset-based paging. Fine at this size; a cursor would be the answer for a large, rapidly
  changing collection, where an insert can shift rows between pages.

## License

[MIT](LICENSE).

---

# ops-core-api (русская версия)

Центральный backend вымышленного мульти-бизнеса (ресторан + wellness-клиника + консалтинг):
клиенты, слоты для брони, бронирования, прайс услуг и база знаний с семантическим поиском
на pgvector.

Это источник правды для четырёх агентских сервисов (voice, RAG, sales, MCP), но он самодостаточен —
обычный HTTP API без единого агентского фреймворка внутри.

## Что умеет

| Возможность | Детали |
|---|---|
| CRM | Поиск клиента по id и по фрагменту имени без учёта регистра |
| Бронирования | Список свободных слотов и создание брони; правило «один слот — одна бронь» проверяется в слое сервисов *и* ограничением в БД |
| Прайс | Расчёт стоимости на количество услуг, скидки применяет взаимозаменяемая политика |
| База знаний | Документ разбивается на чанки и векторизуется при записи; поиск векторизует запрос и находит ближайшие чанки оператором `<=>` |

## Архитектура

Слоистая, со строгим правилом однонаправленных зависимостей: внешние слои зависят от внутренних,
никогда наоборот. Pydantic-схемы живут только на границе HTTP, ниже передаются frozen-dataclass
контракты — сервис никогда не видит ни `Request`, ни SQLAlchemy. Подробности — в
[`docs/architecture.md`](docs/architecture.md), диаграмма слоёв в английской части выше.

| Паттерн | Где | Зачем |
|---|---|---|
| **Repository** | `interfaces/repositories/`, `repositories/` | Сервисы ходят за данными через порты, возвращающие контракты, и не знают про SQL. Вторая реализация — in-memory фейки в тестах. |
| **Factory** | `llm/embedding_factory.py` | Единственное место, где создаётся клиент провайдера. Новый провайдер = новый класс и ветка, сервисы не меняются. |
| **Strategy** | `services/pricing/discount_policies.py` | Правило скидки — внедряемый объект, а не `if quantity > 5`; новая акция не трогает `PricingService`. |
| **Adapter** | `llm/openai_compatible_embedding_client.py` | Оборачивает OpenAI SDK в наш порт `EmbeddingClient`; типы провайдера дальше не проходят. |

`EmbeddingClient` намеренно отделён от клиента генерации текста: это разные зоны ответственности
с разными режимами отказа, а этому сервису нужна только векторизация.

## Быстрый старт

```bash
cp .env.example .env
docker compose up --build
```

Поднимутся Postgres с pgvector и API на <http://localhost:8000>, применятся миграции и загрузятся
демо-данные (6 клиентов, слоты на неделю вперёд, 5 услуг, 5 документов). Swagger — на `/docs`.

**API-ключи не нужны:** `EMBEDDING_PROVIDER` по умолчанию `hashing` — детерминированный локальный
эмбеддер, поэтому семантический поиск работает офлайн сразу после запуска.

## Эндпоинты и примеры

Список путей, примеры `curl` и формат ответов — в английской части выше
([API](#api)); они одинаковы для обеих версий. Чтение открыто, запись требует заголовка `X-API-Key`.

### Пагинация

Все списочные эндпоинты принимают одинаковые `limit` / `offset` (по умолчанию 20, потолок 200) и
возвращают один конверт: `{items, total, limit, offset, has_more}`.

`total` — это то, что делает усечённый ответ честным: без него клиент не отличает «это все свободные
слоты» от «это первые 20 из 56», и агент отвечает клиенту «свободного нет», хотя оно есть. Считается
он по тем же фильтрам, что и `items`, поэтому `?resource_type=meeting_room` показывает число
свободных переговорок, а не всех слотов вообще. `has_more` выводится из остальных трёх — он есть
потому, что LLM-потребитель надёжно читает булево значение и заметно хуже считает арифметику.

Реализация одна на все коллекции: `PaginationParams` и `PageDTO` в `contracts/pagination.py`,
хелпер `paginate()` в `repositories/pagination.py`, который считает и нарезает любой переданный
`select()`, и дженерик-схема `Page[T]`. Репозиторий подключает пагинацию, просто отдав свой запрос в
хелпер — кода пагинации на каждый эндпоинт нет.

`POST /documents/search` намеренно **не** пагинируется: там `top_k`, потому что ранжирование по
релевантности — не коллекция, которую листают, и вторая страница векторного поиска почти всегда
бесполезна.

### Бронь несёт имя, а не аккаунт

`POST /bookings` принимает `guest_name` и слот. Он **не** ссылается на клиента, внешнего ключа
между ними нет.

Это осознанное разделение доменов, а не срезанный угол. `Customer` — это CRM-аккаунт с жизненным
циклом (`lead`, `active`, `churned`), нужный sales- и MCP-флоу. За столиком, забронированным по
телефону, никакого аккаунта нет: ресторану нужно имя на вечер и больше ничего. Прогонять каждую
бронь через find-or-create значило бы плодить аккаунты, которых никто не просил, и ставить лишний
lookup в середину живого звонка.

Хранение имени прямо на брони ещё и фиксирует то, что было сказано. Если клиента потом переименуют,
прошлые брони останутся на то имя, под которым бронировали стол; чтение через внешний ключ переписало
бы историю задним числом.

### Отмена брони

`DELETE /api/v1/bookings/{id}` отменяет бронь и возвращает слот в продажу. Строка не удаляется — у
неё появляется `status: cancelled` и `cancelled_at`, потому что сам факт отмены нужен бизнесу:
опубликованная политика берёт 50% при отмене менее чем за сутки и отдельно считает неявки.

`DELETE`, а не `POST /cancel`, потому что HTTP определяет его идемпотентным — ровно то, что нужно
при обрыве звонка: повторная отмена вернёт ту же бронь и тот же `200`.

Вторая половина — найти, что отменять: UUID по телефону не диктуют. `GET /api/v1/bookings` ищет по
`guest_name`, `date` и `status` (по умолчанию только активные). **Требует ключ даже при открытом
чтении:** свободные слоты и прайс листать безобидно, а список имён гостей со временем визита —
самое чувствительное чтение в этом API.

Одно следствие стоит назвать: на `slot_id` больше нельзя вешать обычный `UNIQUE`, потому что слот
можно забронировать, отменить и забронировать снова. Уникальность стала частичным индексом —
`UNIQUE (slot_id) WHERE status = 'active'` — так что гарантия «без двойных броней» сохраняется, а
история остаётся.

### Повтор брони

`POST /bookings` принимает необязательный заголовок `Idempotency-Key`. Повторный запрос с тем же
ключом возвращает ту же самую бронь и тот же `201`, а не «слот занят».

Это сделано ради войс-агента: телефонный звонок обрывается посреди запроса достаточно часто, чтобы
считать это обычным сценарием, а без ключа повтор неотличим от того, что слот перехватил кто-то
другой — и там, и там `409 slot_unavailable`. С ключом три исхода расходятся:

| Ситуация | Ответ |
|---|---|
| Повтор своего же запроса | `201` с исходной бронью |
| Слот занял кто-то другой | `409 slot_unavailable` |
| Тот же ключ, другие параметры | `409 idempotency_key_reused` |
| Тот же ключ после отмены этой брони | `409 idempotency_key_consumed` |

Ключ лежит в строке брони под уникальным индексом, поэтому два одновременных ретрая физически не
могут вставиться оба — второй отклоняет база, а не приложение, надеющееся успеть заметить.

Ключ расходуется один раз и навсегда. Если в одном звонке забронировать, отменить и забронировать
снова, на вторую бронь нужен новый ключ: повтор старого вернул бы отменённую бронь с кодом `201`,
то есть сказал бы «стол забронирован», пока стол свободен. Ради этого случая и есть
`idempotency_key_consumed` — с запросом всё в порядке, ему просто нужен новый ключ.

Все ошибки приходят в одном конверте:

```json
{ "detail": "Booking slot '...' is already taken.", "error_code": "slot_unavailable" }
```

> **Деньги сериализуются строкой** (`"120.00"`), а не числом: цены — `Decimal` на всём пути, и
> отдавать float значило бы отдавать значение, которое не может точно представить копейки.

## Безопасность

- **API-ключ** — требуется на всех эндпоинтах под `/api/v1`, сравнение через
  `secrets.compare_digest`. Открытыми остаются только `/health` (его опрашивает docker) и
  `/docs` с `/openapi.json` (иначе Swagger UI не отрисуется). Схема опубликована в OpenAPI, поэтому
  в `/docs` работает кнопка **Authorize**.
- Одно правило, объявленное один раз: защита — это `Security()`-зависимость на роутере `/api/v1`,
  поэтому новый роутер нельзя случайно добавить незащищённым, а замок в OpenAPI FastAPI выводит из
  того же объекта, который проверяет ключ — расходиться нечему.
- **Rate limiting** — 60 запросов/минуту на IP и эндпоинт, 20/минуту для двух эндпоинтов,
  вызывающих провайдера эмбеддингов. Счётчики в памяти процесса.
- **CORS** — origins из `CORS_ALLOWED_ORIGINS`, credentials выключены (ключ идёт заголовком, а не куки).
- `API_KEY` в `.env.example` — плейсхолдер `change-me-min-16-chars`. Ровно тот же литерал лежит в
  `.env.example` четырёх агентских сервисов, поэтому `cp .env.example .env` в каждом из пяти даёт
  сходящееся демо. Ключ общий: ротация означает ротацию во всех пяти сразу.

Порядок middleware — `CORS → request_id → api_key → rate_limit`, поэтому отказ возвращается
с CORS-заголовками и request id, а не как непрозрачная ошибка в браузере.

Функция `_requires_api_key()` в `api/v1/middleware/api_key.py` — единственный источник правды:
её применяет middleware, и из неё же генерируется OpenAPI, поэтому замок в Swagger не может
разойтись с тем, что реально проверяет сервер. Отдельный тест дёргает каждый задокументированный
эндпоинт без ключа и сверяет результат со схемой.

### Почему ключ и на чтении

Ключ, попавший в браузер, перестаёт быть секретом: если его несёт React-бандл, он виден в DevTools
и в самом JS. CORS тоже не спасает — его применяет браузер, а `curl` его игнорирует. То есть
варианта «открытое чтение, но безопасно» не существует, как только данные настоящие, а
`notes: "Allergic to lavender oil"` рядом с именем клиента — это перс. данные, по GDPR ещё и
специальной категории.

Одно правило на весь API проще и в рассуждении: нет списка исключений, который надо держать
синхронным, и ничего нельзя случайно оставить открытым.

Для фронтенда ключ живёт в серверном окружении, а API вызывается из route handler или серверного
компонента Next.js — браузер общается только с вашим origin. Никогда не кладите ключ в
`NEXT_PUBLIC_*`: такие переменные вшиваются в клиентский бандл на сборке.

IP-allowlist — хороший дополнительный слой для серверных потребителей, но ключ он не заменяет:
allowlist говорит «с какой машины», ключ — «какой потребитель», и ключ отзывается правкой одной
переменной.

## Эмбеддинги

`hashing` (по умолчанию) — локальные детерминированные векторы: хешируются слова и символьные
n-граммы, с лёгким стеммингом и L2-нормализацией. Совпадение идёт по лексике, не по смыслу: формы
слова он связывает («cancel» находит «cancelled»), синонимы — нет. Для настоящей семантики
переключите `EMBEDDING_PROVIDER` на `openai` или `openai_compatible`; за пределами `llm/` не
меняется ничего.

### Смена провайдера обесценивает индекс

Векторы двух разных моделей лежат в разных пространствах. Косинусное расстояние между ними всё
равно считается, поэтому смена провайдера **не падает** — она тихо начинает возвращать нерелевантные
результаты с нормально выглядящими score. Обе модели 1536-мерные, так что проверка размерности этого
тоже не ловит.

Поэтому каждый чанк хранит модель, которая его векторизовала (`провайдер:модель`, например
`hashing:v1`), а поиск фильтрует по ней прямо в SQL — смешать пространства невозможно
конструктивно. Если сменить провайдера и не переиндексировать, вместо тихого мусора придёт явная
ошибка `embedding_model_mismatch` с указанием обеих моделей и командой для починки
(`python -m src.app.cli.seed --force`).

В отпечатке локального эмбеддера есть версия (`hashing:v1`), потому что смена токенизатора или
стеммера меняет пространство векторов ровно так же, как смена провайдера.

## Разработка

```bash
uv sync && uv run ruff check . && uv run mypy src && uv run pytest
```

Юнит-тесты гоняют сервисы против in-memory фейков всех портов — без БД и сети. Интеграционные
поднимают настоящее приложение через `httpx.AsyncClient`, подменяя только границу БД, так что
роутинг, middleware, валидация и обработка ошибок — боевые. Тесты, которым нужен настоящий
Postgres (запрос `<=>`, блокировка `FOR UPDATE`, экранирование `ILIKE`), пропускаются, пока не
задан `TEST_DB_URL`; в CI поднимается контейнер с pgvector.

Покрытие слоя `services/` проверяется в CI порогом 60% и сейчас составляет 99%.

## Известные ограничения

- Счётчики лимитов в памяти процесса: сбрасываются при рестарте, для нескольких воркеров нужен Redis.
- Один общий ключ на запись, а не полноценная авторизация пользователей.
- Пагинация по offset. На таких объёмах это правильный выбор; для большой и часто меняющейся
  коллекции понадобился бы курсор — при вставке строки сдвигаются между страницами.

## Лицензия

[MIT](LICENSE).
