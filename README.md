# ops-core-api

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
| Bookings | Availability listing and booking creation, with the "one party per slot" rule enforced in the service layer *and* by a database constraint |
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

Reads are open. Writes require the `X-API-Key` header (see [Security](#security)).

| Method | Path | Auth |
|---|---|---|
| `GET` | `/health` | open |
| `GET` | `/api/v1/customers?search=&limit=` | open |
| `GET` | `/api/v1/customers/{id}` | open |
| `GET` | `/api/v1/booking-slots?date=&resource_type=&limit=` | open |
| `POST` | `/api/v1/bookings` | **key** |
| `GET` | `/api/v1/pricing?service=&quantity=` | open |
| `GET` | `/api/v1/pricing/services` | open |
| `POST` | `/api/v1/documents` | **key** |
| `POST` | `/api/v1/documents/search` | open |

### Examples

```bash
API_KEY=$(grep '^API_KEY=' .env | cut -d'"' -f2)

# Service and database status
curl localhost:8000/health
# {"status":"ok","database":"ok"}

# Find a customer
curl "localhost:8000/api/v1/customers?search=anna"

# Free slots for a given day
curl "localhost:8000/api/v1/booking-slots?date=2026-07-24&resource_type=table"

# Price six sessions — the volume discount is applied by the service layer
curl "localhost:8000/api/v1/pricing?service=Deep%20Tissue%20Massage&quantity=6"
# {"service_name":"Deep Tissue Massage","unit_price":"120.00","quantity":6,
#  "subtotal":"720.00","discount_percent":"10","discount_amount":"72.00","total":"648.00"}

# Book a slot (repeat the same call and it returns 409 slot_unavailable)
curl -X POST localhost:8000/api/v1/bookings \
  -H "X-API-Key: $API_KEY" -H 'Content-Type: application/json' \
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

Every error uses one envelope, so a client has a single shape to handle:

```json
{ "detail": "Booking slot '...' is already taken.", "error_code": "slot_unavailable" }
```

> **Money is serialised as a string** (`"120.00"`), not a number. Prices are `Decimal` end to end;
> emitting floats would hand clients a value that cannot represent cents exactly.

## Security

- **API key** — `POST`/`PUT`/`PATCH`/`DELETE` require `X-API-Key`, compared with
  `secrets.compare_digest`. Reads stay open so the demo is browsable. `POST /documents/search` is
  explicitly exempt: it is a read that happens to be a POST because the query does not belong in a URL.
  Swagger UI publishes the scheme, so you can hit **Authorize** in `/docs` and execute the protected
  endpoints from the browser.
- **`PUBLIC_READS`** — set it to `false` and every endpoint except `/health` needs the key. See
  [Who may read](#who-may-read) for when that is the right setting.
- **Rate limiting** — 60 requests/minute per IP per endpoint, and 20/minute for the two endpoints
  that call the embedding provider. In-memory, so counters are per process; the container runs a
  single worker.
- **CORS** — origins from `CORS_ALLOWED_ORIGINS`, credentials disabled (the key travels in a
  header, never a cookie).

Middleware runs `CORS → request_id → api_key → rate_limit`, so a rejection still comes back with
CORS headers and a request id instead of surfacing as an opaque browser error.

`_requires_api_key()` in `api/v1/middleware/api_key.py` is the single source of truth: the
middleware enforces it and the OpenAPI schema is generated from it, so the padlock shown in Swagger
cannot drift from the rule the server actually applies. A test asserts that correspondence by
calling every documented operation unauthenticated.

### Who may read

Reads are open by default, and that is a deliberate choice tied to one fact: **a credential that a
browser holds is not a secret.** If a React bundle carries the key so it can call this API, the key
is visible in DevTools and in the shipped JavaScript — it stops nobody. CORS does not help either;
it is enforced by the browser, so `curl` ignores it completely. Open reads over demo data are the
honest posture; a key in a public SPA would be security theatre.

That changes the moment the data is real. `notes: "Allergic to lavender oil"` next to a customer
name is personal data, and under GDPR health information is a special category — an open
`GET /customers` would be a leak, whatever CORS says.

So pick the posture that matches the deployment:

| | `PUBLIC_READS=true` (default) | `PUBLIC_READS=false` |
|---|---|---|
| Caller | browser talks to this API directly | a server-side caller holds the key |
| Data | demo / fictional | real |
| Reads | open | need the key |
| CORS | matters | irrelevant (no browser involved) |

For a Next.js front end, the second column is the one you want: keep the key in the server
environment and call this API from a route handler or server component, so the browser talks only
to your own origin. Never expose it through a `NEXT_PUBLIC_*` variable — those are inlined into the
client bundle at build time.

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

| Variable | Default | Purpose |
|---|---|---|
| `DB_URL` | — | Postgres async URL |
| `API_KEY` | — | **Required.** Shared secret for protected endpoints |
| `PUBLIC_READS` | `true` | `false` requires the key on reads too |
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
- No pagination; list endpoints take a `limit` and cap it.

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

Все ошибки приходят в одном конверте:

```json
{ "detail": "Booking slot '...' is already taken.", "error_code": "slot_unavailable" }
```

> **Деньги сериализуются строкой** (`"120.00"`), а не числом: цены — `Decimal` на всём пути, и
> отдавать float значило бы отдавать значение, которое не может точно представить копейки.

## Безопасность

- **API-ключ** — `POST`/`PUT`/`PATCH`/`DELETE` требуют `X-API-Key`, сравнение через
  `secrets.compare_digest`. Чтение открыто, чтобы демо можно было листать.
  `POST /documents/search` вынесен в исключения: это чтение, которое сделано POST-ом только потому,
  что запросу не место в URL. Схема опубликована в OpenAPI, поэтому в `/docs` есть кнопка
  **Authorize** и защищённые эндпоинты можно выполнять прямо из браузера.
- **`PUBLIC_READS`** — если поставить `false`, ключ требуется на всех эндпоинтах, кроме `/health`.
  Когда это нужно — ниже, в разделе [Кому можно читать](#кому-можно-читать).
- **Rate limiting** — 60 запросов/минуту на IP и эндпоинт, 20/минуту для двух эндпоинтов,
  вызывающих провайдера эмбеддингов. Счётчики в памяти процесса.
- **CORS** — origins из `CORS_ALLOWED_ORIGINS`, credentials выключены (ключ идёт заголовком, а не куки).

Порядок middleware — `CORS → request_id → api_key → rate_limit`, поэтому отказ возвращается
с CORS-заголовками и request id, а не как непрозрачная ошибка в браузере.

Функция `_requires_api_key()` в `api/v1/middleware/api_key.py` — единственный источник правды:
её применяет middleware, и из неё же генерируется OpenAPI, поэтому замок в Swagger не может
разойтись с тем, что реально проверяет сервер. Отдельный тест дёргает каждый задокументированный
эндпоинт без ключа и сверяет результат со схемой.

### Кому можно читать

Чтение по умолчанию открыто, и это осознанное решение, опирающееся на один факт: **ключ, попавший
в браузер, перестаёт быть секретом.** Если React-бандл несёт ключ, чтобы дёргать этот API, ключ
видно в DevTools и в самом JS — он не защищает ни от кого. CORS тоже не помогает: его применяет
браузер, а `curl` его просто игнорирует. Поэтому на вымышленных данных открытое чтение — честная
позиция, а ключ в публичном SPA был бы имитацией безопасности.

Всё меняется, когда данные настоящие. `notes: "Allergic to lavender oil"` рядом с именем клиента —
это перс. данные, а по GDPR медицинская информация относится к специальной категории; открытый
`GET /customers` был бы утечкой, независимо от CORS.

Поэтому выбирайте режим под развёртывание:

| | `PUBLIC_READS=true` (по умолчанию) | `PUBLIC_READS=false` |
|---|---|---|
| Кто вызывает | браузер напрямую | серверная часть, держащая ключ |
| Данные | демо / вымышленные | реальные |
| Чтение | открыто | нужен ключ |
| CORS | важен | не нужен (браузера в цепочке нет) |

Для фронтенда на Next.js правильный вариант — второй: ключ лежит в серверном окружении, а API
вызывается из route handler или серверного компонента, так что браузер общается только с вашим
собственным origin. Никогда не кладите ключ в `NEXT_PUBLIC_*` — такие переменные на этапе сборки
вшиваются в клиентский бандл.

IP-allowlist — хороший дополнительный слой для серверных потребителей, но он не заменяет ключ:
allowlist говорит «с какой машины», ключ — «какой именно потребитель», и ключ отзывается правкой
одной переменной, а не инфраструктуры.

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
- Нет пагинации; списочные эндпоинты принимают `limit` и ограничивают его сверху.
