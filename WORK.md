# event-service — what to build

## Responsibility
Owns **events** (conferences, workshops, seminars), schedules, capacity.
Database: `event_db` on the shared Mongo.

## Endpoints to implement (mounted under `/events`)
| Method | Path                       | Purpose                                  | Auth |
|--------|----------------------------|------------------------------------------|------|
| POST   | `/events`                  | Create event                             | JWT (organizer) |
| GET    | `/events`                  | List events (filter by date/category)    | none |
| GET    | `/events/{id}`             | Event details                            | none |
| PATCH  | `/events/{id}`             | Update event                             | JWT (organizer/owner) |
| DELETE | `/events/{id}`             | Cancel event                             | JWT (organizer/owner) |
| GET    | `/events/{id}/availability`| Remaining capacity (called by registration-service) | service/JWT |
| POST   | `/events/{id}/reserve`     | Decrement capacity by 1 (called by registration-service when booking is created) | service/JWT |
| POST   | `/events/{id}/release`     | Increment capacity by 1 (called when booking is cancelled) | service/JWT |
| GET    | `/healthz`                 | Liveness/readiness (already done)        | none |

## What it stores in Mongo
Collection `events`: `_id`, `title`, `description`, `category`, `starts_at`, `ends_at`, `location`, `capacity`, `seats_left`, `organizer_id`, `created_at`, `updated_at`.

## How it talks to other services
- **Sync (HTTP) — incoming only**: registration-service hits `/availability` and `/reserve`/`/release` before/after a booking.
- **Async (RabbitMQ)** — exchange `events.exchange`:
  - **Publish**: `event.created`, `event.updated`, `event.cancelled` (notification-service consumes).
  - **Consume**: nothing required for the MVP.
- **JWT validation**: same `JWT_SECRET`. Verify token + check `role` claim for organizer-only routes.

## Env you already have
`MONGO_URL`, `DB_NAME=event_db`, `JWT_SECRET`, `RABBITMQ_URL`, `PORT=8000`.

---

## How to run locally

You need the infra stack up (Mongo + RabbitMQ + sibling services). The infra repo orchestrates everything — you do **not** run event-service alone.

### Option A — full stack via infra
```
cd ../infra
bash scripts/up-dev.sh
```
event-service is at **http://localhost:8002**.
Logs: `docker compose -p events-dev logs -f event-service`

### Option B — code-reload while iterating
1. Start deps:
   ```
   cd ../infra
   docker compose -p events-dev -f compose/docker-compose.yml -f compose/docker-compose.dev.yml up -d mongo rabbitmq
   ```
2. Run event-service on the host:
   ```
   cd ../event-service
   python -m venv .venv && source .venv/Scripts/activate
   pip install -r requirements.txt
   export MONGO_URL=mongodb://localhost:27017
   export RABBITMQ_URL=amqp://guest:guest@localhost:5672/
   export DB_NAME=event_db JWT_SECRET=supersecret SERVICE_NAME=event-service
   uvicorn app.main:app --reload --port 8000
   ```

## After you change code
```
cd ../infra
docker compose -p events-dev -f compose/docker-compose.yml -f compose/docker-compose.dev.yml up -d --build event-service
```

## Definition of done
- CRUD on events works.
- `/reserve` decrements `seats_left` atomically (Mongo `$inc` with a `seats_left > 0` filter), `/release` increments it.
- Domain events are visible in RabbitMQ UI under `events.exchange`.
- `/healthz` returns 200.
