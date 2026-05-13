# Production deploy guide (Yandex Cloud VM)

Текущий хост: Yandex.Cloud VM, публичный IP `158.160.134.168`, Moscow.

Этот документ — пошаговый чек-лист, как из dev-окружения превратить машину в
полноценный продакшен с HTTPS, Telegram webhook, ежедневными бэкапами и
переключением на Clerk Production. Ориентировочное время: **30–60 минут**,
из которых 80% — ожидание DNS пропагации и верификации Clerk.

## 0. Что должно быть до старта

- [ ] Куплен домен (`.ru` за ~200 ₽ на reg.ru / timeweb / 2domains).
- [ ] В DNS-управлении регистратора создана A-запись:
      ```
      Имя:    @
      Тип:    A
      Адрес:  158.160.134.168
      TTL:    600
      ```
      и CNAME для www → `<домен>.`
- [ ] В Yandex Cloud Console → VM → Security Groups открыты входящие:
      | Протокол | Порт | Источник     |
      |----------|------|--------------|
      | TCP      | 80   | `0.0.0.0/0`  |
      | TCP      | 443  | `0.0.0.0/0`  |
- [ ] Куплен (или сгенерён) static-key к Yandex Object Storage (для бэкапов):
      Console → Object Storage → создать bucket `ai-calendar-backups`
      (приватный) → IAM → Service accounts → создать `backup-uploader` с
      ролью `storage.editor` → создать static-key.

Проверка что DNS уже работает:
```bash
dig +short твой-домен.ru
# должно вернуть: 158.160.134.168
```

## 1. Заполнить `.env.prod`

```bash
cd /home/<user>/ai_calendar
cp .env.prod.example .env.prod
nano .env.prod
```

Минимум, что нужно вписать:
- `DOMAIN=твой-домен.ru` и `ACME_EMAIL=ты@твой-домен.ru`
- `ENCRYPTION_KEY=` — НОВЫЙ ключ Fernet (не тот же что в dev!):
  ```bash
  docker run --rm python:3.12-slim python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null
  ```
- `POSTGRES_PASSWORD=` — `openssl rand -hex 24`
- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_live_…` и `CLERK_SECRET_KEY=sk_live_…` —
  см. секцию **3. Clerk Production** ниже
- `YANDEX_API_KEY=`, `YANDEX_FOLDER_ID=` — те же что в dev, либо завести
  отдельный сервис-аккаунт в YC под прод
- `TELEGRAM_BOT_TOKEN=` — тот же бот, что в dev
- `INTERNAL_SERVICE_TOKEN=` — `openssl rand -hex 32` (новый, не из dev)
- `TG_WEBHOOK_SECRET=` — `openssl rand -hex 24`
- `BACKUP_S3_ACCESS_KEY=` / `BACKUP_S3_SECRET_KEY=` — static-key из шага 0

## 2. Запуск контейнеров

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
               --env-file .env.prod up -d --build
```

Что произойдёт:
- web соберётся через `Dockerfile.prod` (next build → standalone).
- backend применит миграции и запустится с `--workers 2`.
- Caddy на `:80/:443` сразу попытается выпустить Let's Encrypt-сертификат
  для `${DOMAIN}`. Это занимает 10–30 секунд (видно в `docker compose logs caddy`).
- tg-bot стартанёт в webhook-режиме и сам зарегистрирует webhook в Telegram.
- backup-контейнер сразу сделает первый дамп в Object Storage и далее
  будет повторять раз в 24 часа.

Проверка:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
curl -I https://твой-домен.ru/                       # должен быть 200/307
curl -I https://твой-домен.ru/api/health 2>&1 | head # backend жив
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
               logs --tail 50 caddy                  # сертификат выписался?
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
               logs --tail 50 backup                 # дамп ушёл?
```

## 3. Clerk Production

В development-инстансе всё работало с `pk_test_…`, но Clerk будет показывать
"Development mode" badge и не гарантирует SLA. Для прода — создать
Production instance:

1. [dashboard.clerk.com](https://dashboard.clerk.com) → твоё приложение →
   слева переключатель **Development / Production** → нажать «**Create
   Production Instance**».
2. Clerk попросит ввести домен (`твой-домен.ru`) и покажет 4 DNS-записи:
   - `clerk` (CNAME) — для Frontend API
   - `accounts` (CNAME) — для Account Portal
   - 2 × CNAME для email (DKIM/SPF)
   В DNS-кабинете регистратора создаёшь все эти записи. Clerk через
   3–60 минут видит их и помечает домен как verified.
3. После верификации → API Keys → копируешь `pk_live_…` и `sk_live_…`
   в `.env.prod`. `CLERK_JWKS_URL` уже в шаблоне правильный
   (`https://clerk.${DOMAIN}/.well-known/jwks.json`), но проверь в
   браузере что он отдаёт `{"keys": [...]}`.
4. Restart web + backend чтобы подцепили новые ключи:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml \
                  --env-file .env.prod up -d --build web backend
   ```

## 4. Telegram webhook

Уже автоматически. После `up -d` в tg-bot-логах будет:
```
INFO  aiogram.dispatcher  webhook set: https://твой-домен.ru/telegram/webhook
```

Если что-то пошло не так, можно проверить вручную:
```bash
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```
Ожидаемый ответ:
```json
{"ok":true,"result":{"url":"https://твой-домен.ru/telegram/webhook", "pending_update_count": 0, ...}}
```

## 5. Что мониторить

Базовый минимум:
- `docker compose ... logs -f caddy backend web tg-bot worker` — пока не
  стабилизируется
- `docker stats` — CPU/RAM по контейнерам
- `df -h` — место (postgres-data пухнет, бэкапы — нет)
- `journalctl -u docker -e` — если docker-демон что-то странно делает

Для дальнейших улучшений: завести Sentry (`SENTRY_DSN` в env), Langfuse для
трейсинга LLM-вызовов (`LANGFUSE_*`), и Uptime Robot / Healthchecks.io для
внешнего мониторинга `https://твой-домен.ru/api/health`.

## 6. Обновления

После `git pull`:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
               --env-file .env.prod up -d --build
```

Compose сам пересоберёт изменённые сервисы. Каркасные сервисы (postgres,
redis, caddy) не тронет, если их образы не менялись.

Если миграции БД новые — backend в `command:` уже делает `alembic upgrade
head` при старте, никаких ручных шагов не нужно.

## 7. Откат

Если что-то поехало, откатываемся к предыдущему git-commit'у:
```bash
git checkout <previous-sha>
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
               --env-file .env.prod up -d --build
```

База остаётся той же (миграции **alembic не умеют автоматически даунгрейдить**;
для отката одной миграции нужно `uv run alembic downgrade -1` руками,
предварительно поднявшись на старой версии backend).

Резервная копия БД на сегодня лежит в Object Storage по пути
`s3://ai-calendar-backups/postgres/YYYY/MM/DD/ai_calendar-YYYY-MM-DDTHH-MM-SSZ.dump.gz`.
Восстановление:
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
               exec backup sh -c "
                 aws --endpoint-url=\$BACKUP_S3_ENDPOINT \
                     s3 cp s3://\$BACKUP_BUCKET/postgres/2026/05/13/ai_calendar-…dump.gz - \
                 | gunzip \
                 | pg_restore --host=postgres --username=\$POSTGRES_USER \
                              --dbname=\$POSTGRES_DB --clean --if-exists
               "
```
