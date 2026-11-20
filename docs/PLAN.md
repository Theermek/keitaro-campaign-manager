# План (этап 2)

Согласовано: гео — одна страна; в редакторе только свои кампании (с префиксом);
при частичном сбое создания кампания остаётся, возвращаем ошибку с её ID.

## Архитектура
```
Браузер (Jinja2-страницы + Alpine.js)
   │  JSON /api/...
FastAPI ──► services (создание кампании, редактор, формула долей)
   │                 │
   │           KeitaroClient (httpx) ──► Keitaro Admin API
   ▼
SQLite (SQLAlchemy + Alembic): снимок офферов потоков, pin, журнал операций
```
Keitaro — единственный источник правды о кампаниях, потоках и долях.
БД хранит только то, чего в Keitaro нет.

### Модули
- `app/config.py` — pydantic-settings, читает `.env`.
- `app/keitaro/client.py` — `KeitaroClient` на httpx. Чтение — любые справочники; запись — только
  `create_campaign`, `create_stream`, `update_stream_offers`. Методов изменения офферов, доменов,
  групп и источников нет вообще.
- `app/keitaro/guard.py` — проверка префикса перед каждым изменяющим вызовом: по `campaign_id`
  (или `stream → campaign_id`) получаем кампанию и сверяем `name` с `CAMPAIGN_PREFIX`.
  Иначе — 403 до отправки запроса в Keitaro.
- `app/services/shares.py` — чистая функция `rebalance(offers) -> offers` (формула из CLAUDE.md).
- `app/services/campaigns.py` — создание кампании.
- `app/services/editor.py` — синхронизация потоков со снимком и публикация.
- `app/api/*.py` — роуты, `app/web/` — шаблоны и статика.
- `alembic/`, `tests/`.

## Конфиг (`.env`)
Уже есть: `KEITARO_API_URL`, `KEITARO_API_KEY`, `CAMPAIGN_PREFIX`, `DATABASE_URL`.
Добавить: `KEITARO_DOMAIN=kylovoa.com`, `KEITARO_GROUP=FORTESTS`, `KEITARO_SOURCE=FORTESTS`
(и `.env.example` без значений-секретов). ID резолвятся через API при первом обращении
и кэшируются в памяти; если имя не найдено — понятная ошибка в `/api/reference`.

## Что храним в БД и зачем
| Таблица | Поля | Зачем |
|---|---|---|
| `stream_offer` | `stream_id`, `campaign_id`, `offer_id`, `offer_name`, `status` (active/removed), `pinned`, `share`, `kt_position`, `updated_at`; уникальность (`stream_id`,`offer_id`) | Keitaro «забывает» удалённые офферы — без снимка нельзя показать removed и сделать bring back; по разнице снимка с Keitaro находим офферы, удалённые прямо в Keitaro; pin в Keitaro не существует; имя нужно для офферов, на которые ключ получает 403 |
| `operation_log` | `created_at`, `method`, `path`, `campaign_id`, `status_code`, `request_body` (без ключа/токена), `error` | Аудит изменяющих запросов к общему рабочему Keitaro |

Не храним: кампании, потоки, офферы целиком (берём из Keitaro), draft-состояние (только на фронте).

## API backend
| Метод | Путь | Что делает |
|---|---|---|
| GET | `/api/reference` | Домен, группа, источник из конфига с резолвленными ID |
| GET | `/api/offers?q=` | Автокомплит: `GET /offers` (кэш 5 мин) → фильтр по id/имени, до 20 штук |
| GET | `/api/campaigns` | Только кампании с префиксом |
| POST | `/api/campaigns` | `{name, geo, offer_id}` → создать кампанию, Flow 1, Flow 2 |
| GET | `/api/campaigns/{id}/streams` | Потоки + синхронизация со снимком (это же кнопка «Fetch streams from KT») |
| POST | `/api/shares/rebalance` | Без состояния: список офферов + действие (add/remove/bring_back) → новые доли. Фронт показывает draft, формула живёт в одном месте |
| PATCH | `/api/streams/{id}/offers/{offer_id}` | `{pinned}` — сохраняет pin, в Keitaro не ходит |
| PUT | `/api/streams/{id}/offers` | «Push to KT»: валидация → `PUT /streams/{id}` → обновить снимок |

### Создание кампании
1. Валидация: `name` начинается с `CAMPAIGN_PREFIX`; `geo` — ISO-2 (`^[A-Z]{2}$`); оффер есть в `GET /offers`.
2. `POST /campaigns` `{name, type:"position", domain_id, group_id, traffic_source_id}` (alias генерирует Keitaro; при 4xx на alias — генерируем из имени).
3. `POST /streams` Flow 1: `schema:"redirect"`, `action_type:"http"`, `https://google.com`, фильтр `country accept [GEO]`.
4. `POST /streams` Flow 2: `schema:"landings"`, `action_type:"http"`, `offers:[{offer_id, share:100}]`.
5. Если шаг 3 или 4 упал — ответ 502 с ID созданной кампании и тем, что не создалось; автоматически не удаляем.

### Синхронизация (fetch)
- Редактируемые потоки — `schema:"landings"`; остальные (Flow 1) показываются внизу как есть, только чтение.
- Оффер есть в Keitaro → `active`, доля из Keitaro (Keitaro главнее).
- Оффер `active` в снимке, но пропал из Keitaro → `removed`, 0%, без пересчёта.
- Оффер `removed` в снимке и снова есть в Keitaro → `active`.
- Сортировка: по убыванию доли, при равенстве — `kt_position`; removed внизу.

### Публикация (push)
1. Guard по префиксу.
2. Проверки: доли целые, сумма active = 100, нет дублей.
3. Защита от гонки: повторно читаем поток из Keitaro и сравниваем с тем, что видел пользователь
   (набор offer_id и доли из запроса `base`); не совпало — 409 «обновите потоки».
4. `PUT /streams/{id}` `{offers:[active...]}` (массив заменяется целиком — проверено).
5. Обновляем снимок; removed остаются в БД.

## Фронт
Jinja2-шаблоны от FastAPI + Alpine.js с CDN, без сборки. Две страницы:
- **Создание**: Name (префикс подставлен и не редактируется), Geo, Offer с автокомплитом, Create.
- **Редактор**: выбор кампании → таблица по потокам (Share с pin, Actions: Remove / Bring back),
  инпут с автокомплитом + Add, жёлтый фон и Push to KT / Cancel в draft, кнопка Fetch streams from KT.
Почему не React/Vue: два экрана, draft-состояние локальное, сборка и отдельный dev-сервер не нужны;
по духу ближе к оригиналу (jQuery-компонент).

## Ошибки и тесты
- Ошибки Keitaro (401/402/403/404/422/5xx, таймаут) → единый `KeitaroError` → JSON `{error, detail}` с понятным текстом; ключ и токен в логах маскируются.
- pytest + respx (Keitaro замокан): формула долей (все примеры из отчёта), guard префикса, создание кампании (включая частичный сбой), sync (удаление в KT, возврат), push (409, сумма ≠ 100).

## Порядок реализации (как в TASK.md, стоп после каждого шага)
1. Каркас: FastAPI, конфиг, KeitaroClient + guard, SQLAlchemy, Alembic (первая миграция).
2. Чтение: `/api/reference`, `/api/offers`, `/api/campaigns`.
3. Создание кампании → проверка в админке → страница.
4. Редактор: просмотр → добавление → удаление (+ pin, bring back).
5. Ошибки, тесты.
6. README.
