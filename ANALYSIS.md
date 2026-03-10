# Системный анализ MyAgent (архив)

> Дата: 2026-03-10  
> ⚠️ Пошаговый план исправлений → [PLAN_V2.md](PLAN_V2.md)

---

## Баги и ошибки

### BUG-1 (Critical): Нарушение формата Anthropic Messages при множественных tool_use

**Файл:** `agent/context.py` → `build_messages()`  
**Проблема:** Каждый `tool_call` записывается как **отдельная** пара assistant/user сообщений. Anthropic API требует, чтобы **все** `tool_use` блоки из одного ответа LLM были в **одном** assistant message, а все `tool_result` — в одном следующем user message.  
**Последствие:** Если LLM вернёт 2+ tool_use блока за раз — API вернёт ошибку невалидного формата.  
**Исправление:** Группировать tool calls из одного ответа LLM в один assistant message и один user message с несколькими tool_result.

---

### BUG-2 (High): Text-only response теряется из контекста

**Файл:** `agent/core.py` → `run()`, строка с `continue`  
**Проблема:** Когда LLM возвращает текст без tools, вызывается `continue` без записи в контекст.  
**Последствия:**
- LLM не видит свой предыдущий текстовый ответ
- Нарушается чередование user/assistant — два user message подряд (Anthropic API вернёт ошибку)
- LLM может зациклиться, повторяя одно и то же  
**Исправление:** Добавить текстовый ответ как assistant message в контекст.

---

### BUG-3 (High): Блокирующий `input()` в async контексте

**Файл:** `agent/core.py` → `_handle_tool_call()`  
**Проблема:** `input()` блокирует event loop. Все корутины (включая MCP heartbeat) замирают.  
**Исправление:** Заменить `input(...)` на `await asyncio.to_thread(input, ...)`.

---

### BUG-4 (Medium): Race condition в Memory

**Файл:** `agent/memory.py` → `_persist()`  
**Проблема:** Нет file locking при записи. Конкурентные вызовы `save()` могут повредить файл.  
**Исправление:** Использовать `fcntl.flock()` (Unix) или `msvcrt.locking()` (Windows), либо `filelock` из PyPI.

---

### BUG-5 (Medium): Молчаливое подавление ошибок в MCPClient.stop()

**Файл:** `agent/mcp_client.py` → `stop()`  
**Проблема:** `except Exception: pass` маскирует реальные проблемы при остановке сервера.  
**Исправление:** Добавить `logger.debug("Error stopping MCP session", exc_info=True)`.

---

### BUG-6 (Low): Нет валидации числовых env-переменных

**Файл:** `agent/config.py` → `load_config()`  
**Проблема:** `int(os.environ.get("LLM_MAX_TOKENS", "4096"))` падает с нечитаемым `ValueError` если пользователь введёт нечисловое значение в `.env`.  
**Исправление:** Обернуть в try/except с понятным сообщением.

---

## Слабые места архитектуры

| # | Проблема | Файл | Влияние |
|---|---|---|---|
| 1 | **Нет retry/backoff** для Anthropic API | `llm_client.py` | 429/500/network errors → агент падает |
| 2 | **Нет reconnect для MCP** | `mcp_client.py` | Падение MCP-сервера → non-recoverable |
| 3 | **Нет таймаутов** на MCP tool calls | `mcp_client.py` | Зависшая страница = зависший агент |
| 4 | **Logging не настроен** | все файлы | `logger.info/warning` в коде, но `basicConfig()` нигде не вызван |
| 5 | **Нет input sanitization** | `core.py` | Пользовательский ввод → LLM без фильтрации (prompt injection) |
| 6 | **`mcp>=1.0.0` не зафиксирован** | `requirements.txt` | Breaking changes при `pip install` |
| 7 | **Нет graceful degradation** | `core.py` | Исключение в tool call пробрасывается вверх вместо возврата ошибки LLM |
| 8 | **Нет static type checking** | весь проект | Аннотации есть, но mypy/pyright не настроены |
| 9 | **Нет CI pipeline** | — | Нет GitHub Actions, pre-commit hooks, линтинга |
| 10 | **Audit log без ротации** | `core.py` | `agent_log.jsonl` растёт бесконечно, нет привязки к сессии |

---

## Что нужно для prod-ready

| Категория | Что нужно | Статус |
|---|---|---|
| **Надёжность** | Retry с exponential backoff для Anthropic API | ❌ |
| **Надёжность** | Timeout для MCP tool calls (60s default) | ❌ |
| **Надёжность** | Reconnect при падении MCP-сервера | ❌ |
| **Надёжность** | Error recovery — ошибки tools → текст для LLM, не crash | ⚠️ частично |
| **Observability** | Structured logging (JSON) с настраиваемым уровнем | ❌ |
| **Observability** | Трекинг расхода токенов за сессию + за задачу | ❌ |
| **Observability** | Session ID для audit log и корреляции | ❌ |
| **Безопасность** | Input sanitization перед отправкой в LLM | ❌ |
| **Безопасность** | Token limit guard — жёсткий лимит на контекст | ❌ |
| **Качество** | mypy / pyright strict mode | ❌ |
| **Качество** | Linter (ruff) + formatter (black/ruff) | ❌ |
| **Качество** | Pre-commit hooks | ❌ |
| **Инфра** | CI pipeline (GitHub Actions) | ❌ |
| **Инфра** | Docker / docker-compose для MCP + agent | ❌ |
| **UX** | Конфигурация через CLI args (не только .env) | ❌ |

---

## Оптимизация расхода токенов

### OPT-1: Не отправлять `thinking` в контекст (экономия ~15-25%)

**Файл:** `agent/context.py` → `build_messages()`  
**Суть:** `thinking` сохраняется в Step и добавляется как text блок в assistant message. Claude **не нуждается** в своих прошлых thinking блоках — они только раздувают контекст.  
**Действие:** Убрать `thinking` из `build_messages()`, оставив только в audit log.

---

### OPT-2: Обрезка result от browser_snapshot (экономия ~30-50%)

**Файл:** новая утилита или `tool_executor.py`  
**Суть:** A11y tree может быть 5000-15000 токенов. Нужна функция `truncate_snapshot(text, max_chars=8000)`:
- Удалять скрытые / aria-hidden элементы
- Обрезать повторяющиеся списки (первые N + `"... and {X} more"`)
- Ограничивать глубину вложенности

---

### OPT-3: Локальная суммаризация вместо LLM-сжатия (экономия 1 LLM call per compression)

**Файл:** `agent/context.py` → `compress_old_steps()`  
**Суть:** Сейчас вызывается `llm_client.send_message()`, тратя ~500-1000 токенов. Заменить на детерминированное сжатие:
```python
summary = "\n".join(f"Step {i}: {s.action}({s.result[:100]})" for i, s in enumerate(old_steps, 1))
```

---

### OPT-4: Убрать описания tools из system prompt (экономия ~300 tokens)

**Файл:** `agent/prompts.py`  
**Суть:** Prompt содержит описания browser tools, но они **уже есть** в JSON-схемах (параметр `tools`). Дублирование. Оставить только правила поведения.

---

### OPT-5: Агрессивнее сжимать старые шаги (порог 15000 вместо 30000)

**Файл:** `agent/core.py`  
**Суть:** Сжатие при 30000 токенов слишком поздно. Снизить до ~15000 и уменьшить `keep_recent` до 7.

---

**Суммарная экономия: ~40-60% токенов на длинных задачах, ~20% на коротких.**

---

## Фичи для удобства и полноценности

### FEAT-1: Smart Retry с самокоррекцией

**Суть:** Когда tool call возвращает ошибку (element not found, timeout), передать ошибку обратно LLM как `tool_result` с `is_error: true`. Claude увидит ошибку и скорректирует действие (например, сделает новый snapshot).  
**Сложность:** Low  
**Файл:** `agent/core.py`, `agent/tool_executor.py`

---

### FEAT-2: Трекер расхода токенов

**Суть:** Накопительный счётчик токенов за сессию/ задачу. Показывать в CLI:
```
✅ Результат: Выполнено. [12 шагов, 45K input, 3.2K output, $0.18]
```
Данные уже есть в `LLMResponse` — нужно только аккумулировать.  
**Сложность:** Low  
**Файл:** `agent/core.py`, `main.py`

---

### FEAT-3: Режим --dry-run / планирование

**Суть:** Агент анализирует задачу и выдаёт **план действий** (5-10 шагов) без выполнения. Пользователь одобряет или корректирует, затем агент выполняет.  
**Реализация:** Отдельный system prompt «only plan, don't execute», один LLM call.  
**Сложность:** Medium  
**Файл:** `agent/core.py`, `agent/prompts.py`

---

### FEAT-4: Подключение к уже открытому браузеру (CDP)

**Суть:** Playwright MCP поддерживает `--cdp-endpoint` для подключения к уже запущенному Chrome. Добавить `CDP_ENDPOINT` в config. Позволит работать с авторизованными сессиями без `--storage-state`.  
**Сложность:** Low  
**Файл:** `agent/config.py`, `main.py`

---

### FEAT-5: Система пользовательских пресетов задач

**Суть:** Файл `presets.yaml` с шаблонами:
```yaml
- name: "Поиск вакансий"
  template: "Найди {count} вакансий '{query}' на {site}"
  defaults: { count: 5, site: "hh.ru" }
```
CLI: `preset вакансии --query "Python developer"`. Не хардкод шагов — шаблоны промптов.  
**Сложность:** Medium  
**Файл:** новый `agent/presets.py`, `main.py`

---

## Варианты использования агента

### USE-1: Мониторинг цен и наличия товаров
Задача: «Проверяй цену на <товар> на <5 магазинов>, если ниже <порога> — уведоми». Агент открывает сайты, находит цены, сравнивает, `remember` для истории.

### USE-2: Автозаполнение форм и подача заявок
Задача: «Заполни заявку на загранпаспорт на gosuslugi.ru, мои данные в памяти». Recall данных → заполнение → confirm перед отправкой.

### USE-3: Агрегация и отчёты из веб-панелей
Задача: «Зайди в Google Analytics, Яндекс.Метрику и CRM, собери данные за неделю, покажи сводку». Авторизация через session persistence, навигация по дашбордам.

### USE-4: Массовая публикация контента
Задача: «Опубликуй пост с текстом X на LinkedIn, Facebook и Telegram Web». Открытие платформ в вкладках, вставка текста, confirm перед публикацией.

### USE-5: QA / Smoke-тестирование веб-приложений
Задача: «Проверь что на staging.myapp.com работают: логин, поиск, корзина, оплата тестовой картой». Прохождение сценария, скриншоты при ошибках, отчёт в done(summary).

---

## Приоритеты

| Приоритет | Задача | Сложность |
|---|---|---|
| 🔴 P0 | BUG-1: multi tool_use в одном сообщении | Medium |
| 🔴 P0 | BUG-2: text-only response в контекст | Low |
| 🟡 P1 | BUG-3: async input() | Low |
| 🟡 P1 | Retry для Anthropic API (3 попытки, backoff) | Low |
| 🟡 P1 | Таймауты на MCP call_tool (60s) | Low |
| 🟡 P1 | OPT-1 + OPT-3: убрать thinking + локальное сжатие | Low |
| 🟡 P1 | OPT-2: обрезка snapshot | Medium |
| 🟢 P2 | BUG-5: логирование ошибок в MCP stop | Trivial |
| 🟢 P2 | BUG-6: валидация числовых env | Trivial |
| 🟢 P2 | Настроить logging | Low |
| 🟢 P2 | FEAT-1: smart retry с is_error | Low |
| 🟢 P2 | FEAT-2: трекер токенов | Low |
| 🟢 P2 | Зафиксировать mcp версию | Trivial |
| 🟢 P3 | FEAT-3: dry-run режим | Medium |
| 🟢 P3 | FEAT-4: CDP endpoint | Low |
| 🟢 P3 | FEAT-5: пресеты задач | Medium |
| 🟢 P3 | OPT-4: убрать дубли tools из prompt | Low |
| 🟢 P3 | CI pipeline + linting | Medium |
