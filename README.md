# AI Calendar

Интеллектуальный календарь-оптимизатор: чат-агент управляет событиями
(локально и через Яндекс Календарь по CalDAV) и подстраивает расписание
под биометрию (Whoop / Apple Watch).

Публичный сайт — **https://ai-calendar.ru**.

## Стек

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, LangGraph,
  Arq, Postgres 16, Redis.
- **Frontend:** Next.js 15 (App Router), React 19, Tailwind, FullCalendar.
- **Telegram-бот:** aiogram 3 (webhook в проде, polling в dev).
- **Auth:** Clerk в проде, dev-режим без ключей для локалки.

## Запуск локально

```bash
cp .env.example .env
docker compose up --build
```

- `http://localhost:8000` — FastAPI (swagger на `/docs`)
- `http://localhost:3000` — Next.js
- Postgres `5432`, Redis `6379`

## Прод

Готовый Caddyfile + `docker-compose.prod.yml` для деплоя на одну VM с
автоматическим TLS через Let's Encrypt. Шаблон секретов — `.env.prod.example`.

## Лицензия

MIT.
