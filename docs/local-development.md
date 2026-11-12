# Локальная разработка и CI

Контур TASK-009 рассчитан на локальную разработку и одноразовые среды GitHub Actions. Нужны Docker Engine с Compose v2.24+ (или Docker Desktop), Bash и OpenSSL. Команды выполняются из корня репозитория.

| Сервис | Как включить | Что доступно в базовой версии |
| --- | --- | --- |
| `db` | По умолчанию | PostgreSQL 16, том `postgres-data`, проверка SQL под ролью приложения |
| `migrate`, `seed`, `api` | `--profile api` | Конфигурация Alembic и FastAPI. Требуется код TASK-005 |
| `frontend`, `api`, `seed`, `migrate` | `--profile web` | Конфигурация Next.js и общего origin. Требуются TASK-005 и TASK-006 |
| `worker`, `seed`, `migrate` | `--profile worker` | Воркер TASK-005 с локальной сводкой и SQL-проверкой подключения. Внешний адаптер относится к TASK-007 |
| `backend-tests` | `--profile ci` | Образ pytest для TASK-005. Запускается разовой командой `run` |

## Первый запуск PostgreSQL

Создайте `.env` один раз. Команда защищает существующий файл от перезаписи.

```bash
(
  set -eC
  umask 077
  printf 'POSTGRES_PASSWORD=%s\nDB_APP_PASSWORD=%s\nAPP_SIGNING_KEY=%s\nWEB_PORT=3000\n' \
    "$(openssl rand -hex 24)" "$(openssl rand -hex 24)" "$(openssl rand -hex 32)" > .env
)
docker compose config --quiet
docker compose up -d --wait --wait-timeout 120 db
docker compose ps
```

Compose завершит проверку конфигурации ошибкой, если обязательные переменные отсутствуют. PostgreSQL слушает сеть контейнеров. Порт хоста для БД не публикуется. Роль `enot_app` может выполнять миграции в схеме `public` базы `enot`, без полномочий суперпользователя, создания ролей и баз. При запуске SQL-проверка устанавливает соединение с БД под этой ролью.

### Переменные

| Имя | Где задаётся | Назначение |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | `.env` | Независимый пароль администратора `postgres` для инициализации БД |
| `DB_APP_PASSWORD` | `.env` | Пароль `enot_app`. Используйте значение из `openssl rand -hex 24`, пригодное для DSN |
| `WEB_PORT` | `.env`, по умолчанию `3000` | Локальный порт Next.js на `127.0.0.1`. Открывайте `http://localhost:<порт>` для согласования с `APP_ORIGIN` |
| `DATABASE_URL` | Compose | DSN SQLAlchemy/psycopg для API, миграций, тестов и воркера |
| `APP_SIGNING_KEY` | `.env`, передаётся только API | Обязательный ключ CSRF и курсоров длиной от 32 байт. Для существующего `.env` добавьте независимое значение `openssl rand -hex 32`. |
| `APP_COOKIE_SECURE` | Локальный Compose для API | `false` при loopback HTTP. Для HTTPS применяется стандартная настройка backend `true`. |
| `TEST_DATABASE_URL` | Сервис `backend-tests` | Подключение к отдельной базе `enot_test`. |
| `APP_ORIGIN` | Compose | Origin браузера для проверки запросов в API |
| `API_INTERNAL_ORIGIN` | Compose и Dockerfile Next.js | Внутренний адрес API для Next.js |
| `AI_PROVIDER` | Compose | `stub` для локального окружения и CI |

PostgreSQL считывает пароли и выполняет SQL инициализации при создании пустого тома. Для существующего тома пароль нужно изменить в PostgreSQL и синхронно обновить `.env`, затем пересоздать затронутые контейнеры. В интерактивном сеансе `docker compose exec db psql -U postgres -d enot` используйте `\password enot_app` или `\password postgres`. Значения из `.env` и полный вывод `docker compose config` могут содержать секреты.

## Остановка

```bash
docker compose --profile '*' stop
docker compose --profile '*' down
```

`stop` оставляет контейнеры, `down` удаляет их и сети проекта. Обе команды сохраняют том. Удаление томов в CI выполняется в отдельном одноразовом проекте.

## Миграции после подключения TASK-005

Перед миграцией существующей базы сделайте резервную копию. Для чистого окружения или проверки на восстановленной копии выполните:

```bash
docker compose --profile api run --build --rm migrate
docker compose --profile api run --rm migrate alembic current
docker compose --profile api run --rm migrate alembic check
docker compose --profile api --profile worker up -d --build --wait --wait-timeout 120 api worker
```

При обычном запуске профиль API автоматически выполняет `alembic upgrade head` и затем разовый сервис `seed` выполняет `python -m enot_api.cli import` до старта API и воркера. Повторный импорт тех же входов возвращает прежний ID выпуска и хеш. Посмотреть результат можно через `docker compose --profile api logs seed`. `alembic current` показывает применённую ревизию. `alembic check` выявляет расхождения, которые Alembic обнаруживает между моделями и схемой БД. Порядок отката зависит от конкретной ревизии. Проверьте `downgrade` на отдельной копии и сверяйте данные до применения. Для миграции с потерей данных используйте резервную копию.

Профиль `web` подключается после появления TASK-006. Создать локальную учётную запись после запуска API можно командой `docker compose exec api python -m enot_api.cli create-user owner`.

Проверки backend запускаются в отдельной базе. В CI одноразовый экземпляр создаёт её командой `docker compose exec -T db createdb -U postgres -O enot_app enot_test`. Владение этой базой позволяет роли создавать и удалять изолированные тестовые схемы. Команда проверки — `docker compose --profile ci run --build --rm backend-tests`.

## Резервное копирование

```bash
(
  set -e
  umask 077
  mkdir -p backups
  archive="$(mktemp backups/enot-XXXXXXXX.dump)"
  if docker compose exec -T db pg_dump -U postgres -d enot -Fc > "$archive"; then
    printf '%s\n' "$archive"
  else
    rm -f "$archive"
    exit 1
  fi
)
```

Архив содержит данные и схему базы `enot`. Роли и их пароли создаются отдельно при инициализации PostgreSQL. Храните копии с ограниченным доступом.

## Восстановление в новый том

Подставьте путь к архиву. Используйте имя нового Compose-проекта, чтобы исходная база оставалась доступна.

```bash
(
  set -eu
  archive=backups/enot-XXXXXXXX.dump
  test -s "$archive"
  export COMPOSE_PROJECT_NAME="enot-restore-$(date +%s)"
  if docker volume inspect "${COMPOSE_PROJECT_NAME}_postgres-data" >/dev/null 2>&1; then
    echo 'Уже есть том проекта восстановления. Выберите новое имя.' >&2
    exit 1
  fi
  docker compose up -d --wait --wait-timeout 120 db
  docker compose exec -T db pg_restore -U postgres -d enot \
    --single-transaction --no-owner --no-privileges --role=enot_app < "$archive"
  docker compose exec -T db psql -U postgres -d enot -c '\dt'
  printf 'Compose-проект восстановления: %s\n' "$COMPOSE_PROJECT_NAME"
)
```

Сверьте число и содержимое ключевых записей, а после подключения backend проверьте `alembic current` и чтение данных через API. Остановить экземпляр можно через `docker compose -p <проект-восстановления> down`. В CI архив с синтетической строкой восстанавливается в отдельную базу PostgreSQL и проверяется чтением строки.

## Диагностика

| Симптом | Действие |
| --- | --- |
| `Set ... in .env` | Сверьте обязательные имена с [шаблоном](../.env.example) и выполните `docker compose config --quiet`. |
| `db` долго в `starting` или `unhealthy` | Проверьте `docker compose logs --tail 80 db`. Сверьте пароль с состоянием тома и проверьте, успешно ли прошла инициализация роли. |
| API или воркер ждёт миграцию | Выполните `docker compose --profile api ps --all` и `docker compose --profile api logs migrate seed`. Проверьте ревизию через `alembic current` и наличие файлов TASK-005. |
| Не собирается образ frontend | Проверьте наличие `frontend/package-lock.json`, скриптов `build` и `start`, а также отсутствие обращений к API из статической сборки. |
| Next.js отвечает, запросы `/api/v1/...` завершаются ошибкой | Проверьте правило rewrite, `docker compose --profile web ps` и готовность API. Для ошибок Origin сверяйте URL браузера с `APP_ORIGIN`. |
| Воркер `unhealthy` | Проверьте `docker compose --profile worker logs worker` и доступ к PostgreSQL. Healthcheck проверяет SQL-соединение, а обработку заданий проверяет сквозной тест CI. |
| Порт интерфейса занят | Измените `WEB_PORT` в `.env` и повторите запуск профиля `web`. |

## CI и интеграция

[Workflow MVP CI](../.github/workflows/ci.yml) запускается в PR и при обновлении `main`. Он проверяет синтаксис Python, существующие тесты калькулятора TASK-003, утверждённый OpenAPI 3.1, все профили Compose и PostgreSQL с синтетическими данными. PR показывает статус и сообщения шагов. При отсутствии `backend/` или `frontend/` в журнале появляется отметка об отложенной проверке. Появление соответствующего каталога включает проверки автоматически. До объединения веток CI PR №5 при отсутствии `backend/` берёт закреплённую версию PR №6. В остальных запусках используются файлы проверяемого коммита.

На машине с Docker проверку PostgreSQL можно повторить командой `COMPOSE_PROJECT_NAME=enot-smoke-$(date +%s) bash infra/postgres/smoke.sh`. Скрипт оставляет отдельный проверочный проект с тестовой строкой и восстановленной базой для осмотра. Остановите его с помощью `docker compose -p <имя-проекта> down`.

| Задача | Стыковка и проверка |
| --- | --- |
| [TASK-005](../architecture/TASK-004/development-plan.md) | Из `/app/backend` запускаются `enot_api.main:app`, Alembic и CLI импорта. Образ сохраняет соседние каталоги TASK-002/003/004 для импорта и OpenAPI. CI проверяет `/readyz`, повтор импорта, вход и каталог из 20 ниш, миграции и pytest. |
| [TASK-006](../tasks/backlog/TASK-006.md) | Сверить путь `frontend/`, npm lock-файл и скрипты Next.js. Настроить rewrite `/api/v1/:path*` на `${API_INTERNAL_ORIGIN}/api/v1/:path*`, сохранить относительные URL в браузере и проверить профиль `web` по `http://localhost:3000`. После подключения CI соберёт образ. |
| [TASK-007](../tasks/backlog/TASK-007.md) | Воркера запускает `python -m enot_api.cli worker`. CI передаёт задание реальному воркеру и проверяет локальный fallback. Для TASK-007 предстоит подключить внешний адаптер и его проверки, затем передать сценарий TASK-008. |
