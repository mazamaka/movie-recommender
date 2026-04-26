# LLM-Reranked Daily Recommendations — Design

**Дата:** 2026-04-26
**Статус:** утверждён, готов к плану реализации
**Автор:** brainstorming session с пользователем

---

## 1. Цель

Сделать ежедневные рекомендации в Telegram-канале **резко релевантнее**, используя:

1. Накопленные реакции в канале (🔥/❤️/🏆/⚡, 👍/🎉/😍/💯, 👎, 💩) — уже собираются в `reaction_feedback.json`.
2. Историю просмотров в Lampa — конкретно поле прогресса `time/duration`, которое сейчас игнорируется.
3. LLM (Claude Sonnet) как **финальный reranker** на топ-кандидатах, с полным контекстом вкуса в промпте.

Изменение пользовательского опыта: вместо «хаотичного» потока 1 фильм каждые 12 часов — **10 целевых рекомендаций ежедневно в 21:00**, формат поста сохраняется (богатый caption + торрент + трейлер + Rezka), у большинства постов добавляется секция «🤖 {обоснование}».

## 2. Не цели (явно out of scope)

- ❌ Никаких embeddings / vector DB / RAG — данных мало (<50 реакций), преждевременно.
- ❌ Никакого fine-tuning / training loop — «обучение» через свежий промпт.
- ❌ Никаких новых форматов поста (медиа-карусель, кнопки навигации) — текущий формат остаётся.
- ❌ Никаких триггеров «по реакции на фильм» — только daily cron.
- ❌ Никакой персонализации per-user — канал один, вкус один.
- ❌ Не парсим Rezka личный кабинет (история берётся из Lampa).

## 3. Контекст текущей системы

**Что уже работает (трогать не будем):**

- `pipeline/runner.py` — полный pipeline sync → enrich → profile → candidates → score → torrent → publish.
- `recommender/content_based.py:score_movie` — content-based скоринг (жанры/актёры/режиссёры/рейтинг/свежесть).
- `publishers/feedback.py` — long-polling реакций каждые 30 сек, накопление в `reaction_feedback.json`, эмодзи-маппинг.
- `publishers/telegram.py:format_message` — богатый формат поста с постером, рейтингами, жанрами, режиссёром, актёрами, торрентом, трейлером, Rezka.
- `ingest/cub_client.py` + `api/v1/sync.py` — забор истории Lampa через CUB API.
- APScheduler в `app.py` — текущий запуск каждые `pipeline_interval_hours = 12`.

**Что недоработано (фиксируем в этой фиче):**

- Реакции используются только для жанрового бонуса (~+0.1 к итоговому score). Актёры, режиссёры, описания, темы, страны — игнорируются.
- Поле `time/duration` из CUB API не извлекается → нет различия между «досмотрел» и «начал и забил».
- Нет LLM нигде в pipeline.

## 4. Архитектура

```
                    ┌─────────────────────────────────────────────┐
                    │         APScheduler (cron 21:00 ежедневно)  │
                    │         misfire_grace_time=3600             │
                    └────────────────────┬────────────────────────┘
                                         ▼
   sync (Lampa CUB) ──→ enrich (TMDB) ──→ build_profile ──→ get_candidates (~80)
                                                                    │
                                                                    ▼
                                                          score_movie  (как сейчас:
                                                            жанры/актёры/режиссёры
                                                            + bayesian + freshness +
                                                            старый feedback bonus)
                                                                    │
                                                                    ▼  shortlist top-30
                                                          ┌─────────┴─────────────┐
                                                          │  llm_reranker.rerank()│  ← НОВОЕ
                                                          │   • taste summary     │
                                                          │   • Sonnet 4.x + cache│
                                                          │   • → top-10 + reason │
                                                          └─────────┬─────────────┘
                                                                    ▼
                                                          torrent search → publish
                                                          (caption + "🤖 {reason}")
```

**Ключевые принципы:**

- LLM врезается **одной точкой** между ranking и торрент-поиском.
- Свежесть «обучения» обеспечивается **автоматически**: каждый день промпт строится из актуальных `reaction_feedback.json` + текущего сигнала `finished/dropped`. Никакого fine-tuning.
- Любая ошибка LLM → **fallback** на `shortlist[:10]` без `llm_reason`. Pipeline не падает никогда.

## 5. Компоненты

### 5.1 Новый модуль `src/movie_recommender/recommender/llm_reranker.py`

**Публичный API:**

```python
async def rerank_candidates(
    candidates: list[dict],          # top-30 from score_movie, sorted desc by score
    feedback: dict[str, dict],        # reaction_feedback.json content
    finished_movies: list[dict],      # enriched history items with time/duration > 0.80
    dropped_movies: list[dict],       # enriched history items with 0.10 ≤ ratio ≤ 0.50
    top_n: int = 10,
) -> list[dict]:
    """Rerank candidates via Claude. Returns top_n with optional 'llm_reason'/'llm_rank'.

    Falls back to candidates[:top_n] (без llm_reason) при любой ошибке.
    """
```

**Внутренние хелперы:**

- `_build_taste_summary(feedback, finished_movies, dropped_movies) -> str` — компактное текстовое описание вкуса (5 секций, см. ниже).
- `_build_candidate_list(candidates) -> str` — нумерованный список топ-30 с метаданными.
- `_parse_llm_response(raw, candidates, top_n) -> list[dict]` — извлекает `picks` из JSON, мапит `tmdb_id` → исходные dict'ы, добивает из shortlist при недоборе.

**Контракт fallback (early returns без вызова Claude):**

| Условие | Возврат | Лог-уровень |
|---|---|---|
| `not settings.anthropic_api_key` | `candidates[:top_n]` | DEBUG |
| `not settings.llm_rerank_enabled` | `candidates[:top_n]` | DEBUG |
| `len(candidates) <= top_n` | `candidates` (как есть) | DEBUG |
| `not feedback and not finished_movies` | `candidates[:top_n]` | INFO |

### 5.2 Формат `_build_taste_summary`

```
ДОСМОТРЕЛ ДО КОНЦА В LAMPA (>80%, сильный позитив):
  - Дюна 2 (2024) [фантастика, приключения]
  - Оппенгеймер (2023) [драма, история]

БРОСИЛ ПОСРЕДИНЕ В LAMPA (10-50%, не зашло):
  - Барби (2023) [комедия, фэнтези] — 22%
  - Мегалополис (2024) [драма] — 35%

ЛЮБИМЫЕ В КАНАЛЕ (🔥/❤️/🏆/⚡):
  - Гладиатор II (2024) [боевик, драма, история]

ПОНРАВИЛИСЬ В КАНАЛЕ (👍/🎉/😍/💯):
  - Топ Ган: Мэверик (2022) [боевик, драма]

НЕ ПОНРАВИЛИСЬ В КАНАЛЕ (👎):
  - Барби (2023) [комедия, фэнтези]

ЗАБЛОКИРОВАНЫ (💩 — не показывать похожее):
  - Мегалополис (2024) [драма, фантастика]
```

**Почему текст а не JSON:** компактнее, читается LLM лучше, видны жанры в скобках. Объём ~30-50 строк, ~500-1000 токенов.

### 5.3 Формат `_build_candidate_list`

```
КАНДИДАТЫ ДЛЯ ПОДБОРКИ НА СЕГОДНЯ (выбери ровно 10 лучших по моему вкусу):

1. Конклав (2024)
   Жанры: триллер, драма
   Режиссёр: Эдвард Бергер
   В ролях: Рэйф Файнс, Стэнли Туччи
   Рейтинг IMDB: 7.6 (120K голосов)
   Описание: После смерти Папы Римского кардиналы собираются для выбора...

2. ...
```

### 5.4 Промпт (структура для prompt caching)

Сборка в порядке:

1. **System prompt** (статика, `cache_control: ephemeral`) — роль рекомендателя, требования к JSON output, формат ответа.
2. **Taste summary** (меняется при новых реакциях, `cache_control: ephemeral`) — секции вкуса.
3. **Candidates** (всегда меняется) — список из 30.

При 1 запуске/день кэш TTL (5 мин) почти не сработает, но caching включаем для будущих расширений (если введём дополнительные вызовы) и для дебага.

### 5.5 Формат ответа LLM (JSON)

```json
{
  "picks": [
    {
      "rank": 1,
      "tmdb_id": 974576,
      "reason": "Эпическая историческая драма с Файнсом — попадает в твою любовь к серьёзному кино масштаба «Дюны» и «Гладиатора»."
    },
    {
      "rank": 2,
      "tmdb_id": 426063,
      "reason": "Атмосферный готический хоррор от Эггерса — стиль и эпоха близки твоим лайкам."
    }
  ]
}
```

### 5.6 Парсинг ответа (`_parse_llm_response`)

| Случай | Действие |
|---|---|
| Валидный JSON, 10 picks с известными tmdb_id | Возврат 10 фильмов с `llm_reason`/`llm_rank` |
| Валидный JSON, picks < top_n | Берём что есть, добиваем из shortlist (без reason) |
| Валидный JSON, picks > top_n | Обрезаем до `top_n` |
| Pick с неизвестным tmdb_id | Игнорируем pick, добиваем из shortlist |
| Pick без `reason` | Оставляем фильм с `llm_reason=None` |
| Дубли rank или rank вне 1..top_n | Игнорируем поле `rank`, используем порядок в массиве picks |
| Невалидный JSON | Fallback на `shortlist[:top_n]` |

### 5.7 Конфигурация (`core/config.py` — новые поля)

```python
# LLM reranker
anthropic_api_key: str = ""
llm_model: str = "<TBD-в-плане>"  # exact ID Sonnet 4.x — проверить через docs.claude.com или claude-api skill в момент имплементации
llm_rerank_enabled: bool = True
llm_rerank_shortlist_size: int = 30
llm_max_tokens: int = 2000
llm_timeout_seconds: int = 60

# Lampa progress thresholds
finished_threshold: float = 0.80
dropped_min_threshold: float = 0.10
dropped_max_threshold: float = 0.50

# Schedule
pipeline_cron_hour: int = 21
pipeline_cron_minute: int = 0
```

### 5.8 Правки в существующих файлах

**`pipeline/runner.py`** (после `scored.sort(...)`):

```python
if settings.llm_rerank_enabled and scored:
    from movie_recommender.recommender.llm_reranker import rerank_candidates
    from movie_recommender.publishers.feedback import get_feedback
    shortlist = scored[:settings.llm_rerank_shortlist_size]
    finished_movies = [m for m in enriched if m.get("tmdb_id") in signals.get("finished", set())]
    dropped_movies = [m for m in enriched if m.get("tmdb_id") in signals.get("dropped", set())]
    scored = await rerank_candidates(shortlist, get_feedback(), finished_movies, dropped_movies, top_n=top_n)
```

**`pipeline/runner.py:_get_sync_history`** (расширить signals):

```python
finished = set()
dropped = set()
for item in items:
    tmdb_id = item.get("tmdb_id")
    duration = item.get("duration") or 0
    time_watched = item.get("time") or 0
    if not tmdb_id or duration <= 0:
        continue
    ratio = time_watched / duration
    if ratio > settings.finished_threshold:
        finished.add(tmdb_id)
    elif settings.dropped_min_threshold <= ratio <= settings.dropped_max_threshold:
        dropped.add(tmdb_id)

signals["finished"] = finished
signals["dropped"] = dropped
```

**Зависимость:** `time`/`duration` должны прокидываться через `api/v1/sync.py` из CUB-ответа без потерь. **Discovery-task в плане:** проверить запросом к `https://cub.rip/api/timeview` или эквиваленту что эти поля приходят. Если их там нет — нужен отдельный CUB endpoint (timeline/timetable).

**`publishers/telegram.py:format_message`** (после description, перед торрент-секцией):

```python
if movie.get("llm_reason"):
    lines.append(f"🤖 <i>{movie['llm_reason']}</i>")
    lines.append("")
```

**`app.py`** (заменить IntervalTrigger на CronTrigger):

```python
from apscheduler.triggers.cron import CronTrigger
scheduler.add_job(
    run_pipeline,
    CronTrigger(hour=settings.pipeline_cron_hour, minute=settings.pipeline_cron_minute),
    misfire_grace_time=3600,
    coalesce=True,
)
```

**`pyproject.toml`** — новая зависимость:

```
"anthropic>=0.40",
```

**`.env.example`** — добавить `ANTHROPIC_API_KEY=`.

### 5.9 Безопасность / логирование

- `ANTHROPIC_API_KEY` только через env, никогда в коде/логах.
- Структурированные логи (existing `structlog`):

```
INFO  llm_rerank_started     candidates=30, feedback_count=12, finished_count=8
INFO  llm_rerank_completed   picked=10, with_reason=10, model=..., input_tokens=2150, output_tokens=850, latency_s=8.4
WARN  llm_rerank_failed      error=TimeoutException, fallback=shortlist
```

- Полный prompt/response **не логируются**. Опциональный флаг `LLM_DEBUG_LOG=true` для дампа в `data/llm_debug/{date}.json` (в .gitignore).

## 6. Потоки данных

### Daily flow (cron 21:00)

```
1. _get_sync_history     →  items + signals (включая finished/dropped) — ~1с
2. _enrich_movies         →  enriched_history с TMDB-метаданными — ~15с
3. build_profile          →  profile (genre/actor/director weights) — мс
4. _get_candidates        →  candidates ~80 — ~25с
5. SCORING + DEDUP        →  scored ~30-60 (с фильтрами) — мс
6. ★ LLM RERANK           →  reranked top-10 (с llm_reason) — 5-15с
7. TORRENT SEARCH         →  recommendations с торрентами — 30-60с
8. PUBLISH                →  Telegram + Rezka comments — ~60с

Total: ~2-3 минуты, completes ~21:03
```

### Состояние на диске (Docker volume `/app/data`)

| Файл | Кто пишет | Когда | Используется |
|---|---|---|---|
| `published_messages.json` | `save_published()` | в шаге 8 | dedup в шаге 5 (next day) |
| `reaction_feedback.json` | `_process_reaction(_count)` | непрерывно (poll loop) | как `feedback` в LLM-промпте |
| `poll_offset.json` | `poll_reactions()` | каждые 30 сек | продолжение polling |
| `data/llm_debug/{date}.json` (опц) | `llm_reranker` если debug | в шаге 6 | manual review |

LLM **не пишет состояние на диск**. «Обучение» = свежий контекст в каждом промпте.

## 7. Ошибки и устойчивость

### Матрица отказов LLM-слоя

| Класс ошибки | Действие | Лог |
|---|---|---|
| `ANTHROPIC_API_KEY` пустой | early return shortlist | DEBUG |
| `LLM_RERANK_ENABLED=false` | early return shortlist | DEBUG |
| `len(candidates) <= top_n` | возврат как есть | DEBUG |
| feedback пуст и finished пуст | early return shortlist | INFO |
| `httpx.TimeoutException` (>60s) | fallback shortlist | WARNING |
| `anthropic.APIStatusError` | fallback shortlist | WARNING |
| `anthropic.RateLimitError` | fallback shortlist | WARNING |
| `anthropic.APIConnectionError` | fallback shortlist | WARNING |
| Невалидный JSON | fallback shortlist | WARNING (+200 символов raw) |
| Нет `picks` в JSON | fallback shortlist | WARNING |
| Чужой `tmdb_id` от LLM | пропуск pick, добор из shortlist | INFO |
| picks короче top_n | добор из shortlist | INFO |
| picks длиннее top_n | обрезка до top_n | INFO |
| picks без `reason` | `llm_reason=None` для этой записи | DEBUG |

**Все** случаи приводят к рабочей публикации.

### Pipeline-уровень

| Ситуация | Поведение |
|---|---|
| 21:00 — pipeline уже бежит | APScheduler `coalesce=True` пропускает дубль |
| 21:00 — нет интернета | TMDB/CUB падают → нечего публиковать (как сейчас) |
| 21:00 — Telegram лежит | `publish_recommendation` логгирует error, возвращает None |
| Старт контейнера в 21:05 | `misfire_grace_time=3600` компенсирует пропуск ≤1ч |

### Стоимость

- 1 LLM call/день, ~$0.02-0.05/вызов с caching → **~$1-3/мес**.
- Жёсткий бюджет не вводим. Tracking через лог `usage.input_tokens` / `usage.output_tokens`.

## 8. Тестирование

### Unit `tests/unit/recommender/test_llm_reranker.py` (10 кейсов)

1. `test_happy_path_returns_top_n_with_reasons`
2. `test_no_api_key_returns_shortlist`
3. `test_disabled_returns_shortlist`
4. `test_empty_feedback_and_no_finished_returns_shortlist`
5. `test_short_candidates_returns_as_is`
6. `test_timeout_falls_back`
7. `test_api_error_falls_back`
8. `test_invalid_json_falls_back`
9. `test_partial_picks_filled_from_shortlist`
10. `test_unknown_tmdb_id_skipped`

### Unit `tests/unit/pipeline/test_runner_progress.py` (5 кейсов)

1. `test_finished_above_80_percent`
2. `test_dropped_in_10_to_50_range`
3. `test_grey_zone_excluded` (0.55, 0.70, 0.79)
4. `test_below_10_percent_excluded`
5. `test_missing_duration_excluded` (защита от ZeroDivisionError)

### Integration `tests/integration/test_pipeline_with_llm.py` (3 кейса)

1. `test_pipeline_calls_llm_with_top_30`
2. `test_pipeline_continues_on_llm_failure`
3. `test_format_message_handles_missing_reason`

### Smoke на проде (вручную после деплоя)

1. `grep "llm_rerank_completed"` в логах — есть с разумными tokens.
2. `grep "llm_rerank_failed"` — пусто или с понятной причиной.
3. Telegram канал в 21:00 — публикуется 10 фильмов.
4. У большинства постов есть «🤖 ...».
5. Через неделю — соотношение позитивных/негативных реакций должно расти.

### Не тестируем (YAGNI)

- ❌ Содержательное качество подбора (subjective, проверяется через реакции).
- ❌ Сам Anthropic SDK.
- ❌ Prompt regression tests (промпт будет эволюционировать).
- ❌ LLM eval-suite.

## 9. План раскатки

1. Реализация локально (новый модуль + правки в 4 файлах + тесты).
2. `pytest tests/` зелёный.
3. Deploy через Portainer API (stack movie-recommender — нужно уточнить ID на проде).
4. `ANTHROPIC_API_KEY` через Portainer env.
5. Manual trigger pipeline (через `/api/v1/pipeline/run` если есть, или ребут контейнера около 21:00).
6. Проверка smoke-чеклиста.
7. Через 1 неделю — анализ логов + реакций, при необходимости тюнинг (`llm_rerank_shortlist_size`, промпт).

## 10. Открытые вопросы (для плана реализации)

1. **Lampa CUB API возвращает `time`/`duration`?** — discovery-task: один реальный запрос к `cub.rip/api/timeview` (или эквиваленту), фиксация формата. Если нет — найти правильный endpoint.
2. **Точный ID модели Sonnet 4.x на момент имплементации** — проверить через `claude-api` skill / docs.claude.com. Внести в `settings.llm_model`.
3. **Stack ID на Portainer для movie-recommender** — нужен для деплоя через API (deployer agent).

---

**Конец дизайна.**
