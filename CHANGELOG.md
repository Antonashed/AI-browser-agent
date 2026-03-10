# CHANGELOG

## [2026-03-10] — Гибридный подход: Haiku + Sonnet

- Дефолтная модель — `claude-3-5-haiku-20241022` (в 4× дешевле, выше rate limit)
- Сильная модель — `claude-sonnet-4-20250514` (для сложных задач)
- `config.py`: добавлен `llm_model_strong` + env `LLM_MODEL_STRONG`
- `llm_client.py`: `set_model()`, `get_model()`, `reset_model()` для переключения
- `core.py`: авто-эскалация на сильную модель после 3 подряд ошибок
- `main.py`: команда `/strong <задача>` для принудительного запуска на Sonnet
- `cli.py`: модель отображается в баннере, `/strong` в справке
- После каждой задачи модель автоматически сбрасывается на дефолтную
- 89 тестов проходят

## [2026-03-10] — Максимальная экономия токенов

- `tool_executor.py`: MAX_SNAPSHOT_CHARS 8000 → 4000 (снапшоты вдвое компактнее)
- `context.py`: MAX_RESULT_CHARS=3000 — обрезка tool_result при добавлении в контекст
- `context.py`: `_truncate_args()` — строковые значения args > 200 символов обрезаются в истории
- `context.py`: MAX_SUMMARY_CHARS 4000 → 2000
- `core.py`: порог компрессии 15000 → 6000, keep_recent 7 → 4
- `llm_client.py`: `_retry_delay()` — при RateLimitError (429) ждать 60с вместо backoff
- `tools.py`: whitelist MCP tools — отправляются только 13 актуальных из 22
- `.env`: LLM_MAX_TOKENS 4096 → 2048
- 89 тестов проходят

## [2026-03-10] — Бесконечные retry для LLM-запросов

- `llm_client.py`: `send_message()` и `send_message_stream()` теперь используют `while True` вместо ограниченного числа попыток
- Экспоненциальный backoff с потолком `MAX_RETRY_DELAY = 30` секунд
- Убраны константы `MAX_RETRIES` и `RETRY_DELAYS`
- 89 тестов проходят

## [2026-03-10] — Переход на standalone режим (MCP запускает свой Chromium)

- Удалён CDP-режим: убраны `cdp_endpoint` из `Config`, `_parse_cdp_endpoint()`, `CDP_ENDPOINT` из `.env`/`.env.example`
- `main.py`: упрощена логика запуска MCP — всегда standalone (viewport, headless, storage)
- `cli.py`: `print_connecting()` упрощён под standalone
- `start.bat`: убран запуск Chrome с `--remote-debugging-port`
- Удалён `test_live.py` (CDP-тестовый скрипт)
- Удалены 4 теста `TestCDPEndpoint` из `test_config.py`
- Обновлены `README.md` и `.env.example`
- 89 тестов проходят

## [2026-03-10] — Поддержка VPN-прокси для Anthropic API

- Добавлена настройка `ANTHROPIC_PROXY` в config и `.env.example`
- `LLMClient` принимает параметр `proxy` и создаёт `httpx.Client`/`httpx.AsyncClient` с прокси
- Запросы к Anthropic API идут через прокси, MCP работает локально без прокси

## [2026-03-10] — Логирование в отдельный файл

- Добавлены настройки `LOG_FILE` и `LOG_LEVEL` в config и `.env.example`
- Если `LOG_FILE` указан — логи пишутся в файл, терминал остаётся чистым для Rich UI
- Для просмотра логов в реальном времени: `Get-Content agent.log -Wait -Tail 50`

## [2025-07-18] — Обновление README

- Полностью переписан README.md: добавлены ключевые фичи (zoning, memory, safety, streaming), подробная установка, быстрый старт, таблица slash-команд, обновлённая архитектура

## [2026-03-10] — Генеральное ревью перед ручными тестами

- Полный code review всех модулей `agent/` и тестов `tests/`
- Удалён дублирующийся `return zones` (мёртвый код) в `agent/page_parser.py`

## [2026-03-10] — Блок 16: Page Zoning + Prompt Improvements

- **Page Parser** (`agent/page_parser.py`): Новый модуль — парсинг a11y tree по ARIA landmark ролям (banner, navigation, main, contentinfo и др.); `parse_zones()`, `zone_summary()`, `extract_zone()`; вложенные landmarks остаются дочерними элементами родительской зоны; fallback в зону `page` если нет landmarks
- **Compound Tools** (`agent/tools.py`): `page_overview` — компактный обзор зон страницы с кол-вом элементов; `get_zone` — получение a11y tree конкретной зоны; вынесены в отдельный список `COMPOUND_TOOLS` (не ломают `merge_tools` и существующие тесты); добавлена `get_all_tools()` для объединения MCP + custom + compound
- **Tool Routing** (`agent/tool_executor.py`): `page_overview` → MCP browser_snapshot → zone_summary; `get_zone` → MCP browser_snapshot → extract_zone с truncation; backward compatibility browser_snapshot сохранена
- **System Prompt** (`agent/prompts.py`): 3 новые секции — «Page Observation Strategy» (page_overview → get_zone workflow), «Scrolling & Dynamic Content» (скролл + re-observe для SPA/lazy-loading), «Efficient Navigation» (вкладки для batch-парсинга)
- **main.py**: `merge_tools` → `get_all_tools` для включения compound tools
- 15 новых тестов: 5 parser (zones, counts, fallback, summary, empty), 5 extract (main, nav, all, missing, label), 4 executor (overview, zone filtered, zone all, zone missing), 1 truncate

## [2026-03-10] — Блок 14: Функциональные доработки (CAPTCHA, аудит, маскирование, метрики)

- **CAPTCHA/2FA** (`prompts.py`, `events.py`): Добавлены инструкции в system prompt для обнаружения CAPTCHA/reCAPTCHA/2FA → остановка + `ask_user()`; новый `EventType.CAPTCHA_DETECTED`
- **Payment Safety** (`prompts.py`): Эксплицитное правило — NEVER execute payment/checkout без `confirm()`
- **Session ID** (`core.py`): `run()` генерирует UUID `session_id`; включается в каждую запись `agent_log.jsonl`
- **Audit Export** (`core.py`): Метод `export_audit()` — фильтрует записи по `session_id` из лог-файла
- **Secret Masking** (`core.py`): `_mask_sensitive()` — маскирует значения из Memory, где ключ содержит password/token/key/secret → `***MASKED***` в audit log (и args, и result)
- **Session Metrics** (`core.py`, `main.py`): `export_metrics()` возвращает `{session_id, task, steps, input_tokens, output_tokens, errors_count, duration_seconds, success}`; `main.py` сохраняет метрики в `session_metrics.jsonl`
- 9 новых тестов: session_id в audit log, маскирование секретов, export_metrics (success + failure), export_audit, CAPTCHA keywords в prompt, payment stop в prompt, CAPTCHA_DETECTED event, SENSITIVE_KEY_PATTERNS

## [2026-03-10] — Ревью и отладка

- **BUG** (`main.py`): Исправлена команда `/go` без плана — раньше "/go" молча отправлялась как задача агенту вместо показа ошибки; переписана на `if/else` с корректной обработкой
- **FIX** (`.gitignore`): Исправлена опечатка `/__pycahce__` → `__pycache__/`
- **FIX**: Создан `pyproject.toml` с конфигурацией pytest-asyncio (`asyncio_default_fixture_loop_scope = "function"`) — убран deprecation warning

## [2026-03-10] — Блок 13: Bugfix + CLI Redesign + Streaming

### Phase 1: Bug Fixes
- **BUG-1.1** (`context.py`, `core.py`): `Step` получил поле `args` → `build_messages()` передаёт реальные аргументы инструментов вместо `{}`, `estimate_tokens()` учитывает args
- **BUG-1.2** (`llm_client.py`): Retry для 529 Overloaded — ловится через `APIStatusError` с `status_code=529` (в SDK v0.52 нет отдельного `OverloadedError`)
- **BUG-1.3** (`core.py`): Защита от бесконечного цикла text-only ответов — nudge при 3, abort при 5 подряд
- **BUG-1.4** (`context.py`): `MAX_SUMMARY_CHARS=4000` — summary обрезается при переполнении, предотвращая бесконтрольный рост
- **BUG-1.5** (`core.py`): Circuit breaker — 5 consecutive errors → автоматический abort с сообщением

### Phase 2: Streaming + Event System
- **events.py** (NEW): `AgentEvent(type, data)` + `EventType` enum — thinking_delta, text_delta, tool_start, tool_result, ask_user, confirm, done, error, status
- **llm_client.py**: `send_message_stream()` — async generator поверх `AsyncAnthropic.messages.stream()`, yields `AgentEvent` для thinking/text deltas, финальный `LLMResponse`; retry logic переиспользуется
- **core.py**: `AgentLoop.__init__` принимает `on_event: Callable | None`; `_get_response()` маршрутизирует streaming/sync; `_handle_tool_call()` emit'ит события вместо print(); таймер на каждый tool call

### Phase 3: Rich CLI
- **requirements.txt**: +`rich==14.0.0`
- **cli.py** (NEW): `CLI` класс — Rich-based UI: `print_banner`, `print_help`, `handle_event`, `print_result`, `print_usage`, `print_session_cost`, `print_history`, `prompt_task`
- **main.py**: полный рефакторинг — slash-команды (`/help`, `/memory`, `/plan`, `/go`, `/history`, `/cost`, `/exit`), session-level usage tracking, Rich UI, streaming events

## [2026-03-10] — Блок 12: UX + полировка

- **BUG-6** (`config.py`): Валидация числовых env — `_parse_int()` с понятным `ValueError` вместо голого `int()` для `LLM_MAX_TOKENS`, `MAX_AGENT_STEPS`, `BROWSER_VIEWPORT_*`, `MAX_EMAILS_TO_SCAN`, `MAX_VACANCIES`
- **BUG-5** (`mcp_client.py`): Логирование ошибок в `stop()` — уже реализовано в блоке 9 (`logger.debug` с `exc_info=True`)
- **Signal handling** (`main.py`): `KeyboardInterrupt` корректно перехватывается при `input()` и `agent.run()`, `finally` гарантирует `mcp.stop()`
- **CLI подсказка** (`main.py`): При ошибке CDP-подключения — понятное сообщение с командой запуска Chrome (уже реализовано в блоке 8)
- **Русские алиасы** (`main.py`): Добавлены `план <задача>` и `выполняй` как алиасы для `plan` / `go`
- 2 новых теста: `test_invalid_int_raises`, `test_invalid_viewport_raises`

## [2026-03-10] — Блок 11: Фичи (smart retry, трекер токенов, dry-run)

- **FEAT-1** (`context.py`, `core.py`, `tool_executor.py`): Smart Retry — `Step` получил поле `is_error`, ошибочные tool_result отправляются с `is_error: true` в Anthropic API; ошибки в `tool_executor` возвращаются с префиксом `[ERROR]`
- **FEAT-2** (`core.py`, `main.py`): Трекер расхода токенов — `AgentLoop` аккумулирует `input_tokens`/`output_tokens`/`steps`, метод `get_usage()`; CLI выводит статистику после каждой задачи
- **FEAT-3** (`prompts.py`, `core.py`, `main.py`): Режим dry-run — `PLAN_PROMPT` + метод `plan(task)` для генерации плана без выполнения; CLI команда `plan <задача>`, затем `go` для запуска
- 5 новых тестов: `test_error_result_has_is_error_flag`, `test_success_result_no_is_error_flag`, `test_usage_tracking`, `test_plan_returns_text` + расширение существующих

## [2026-03-10] — Блок 10: Оптимизация токенов

- **OPT-1** (`context.py`): `thinking` убран из `build_messages()` и `estimate_tokens()` — остаётся только в audit log, экономия ~15-25%
- **OPT-3** (`context.py`): `compress_old_steps()` — детерминированная локальная суммаризация по умолчанию (без LLM call), `keep_recent=7`; LLM-сжатие доступно при передаче `llm_client`
- **OPT-5** (`core.py`): порог сжатия снижен с 30000 до 15000 токенов — раньше срабатывает, меньше расход
- **OPT-2** (`tool_executor.py`): `_truncate_snapshot()` обрезает a11y tree `browser_snapshot` до 8000 символов с маркером `[truncated]`
- **OPT-4** (`prompts.py`): убраны секции «Browser Tools» и «Custom Tools» из system prompt — описания уже есть в JSON-схемах, экономия ~300 токенов
- 2 новых теста: `test_truncate_snapshot_short`, `test_truncate_snapshot_long`

## [2026-03-10] — Блок 9: Надёжность (retry, таймауты, logging)

- **Retry с backoff** (`llm_client.py`): 3 попытки с задержкой 1→2→4с для 429/500/529/APIConnectionError; 401/403 — сразу raise
- **Таймаут MCP** (`mcp_client.py`): `call_tool()` получил параметр `timeout=60.0`, оборачивает вызов в `asyncio.wait_for()`
- **Logging** (`main.py`): `logging.basicConfig()` с форматом `HH:MM:SS [LEVEL] name: message`
- **MCP stop() логирование** (`mcp_client.py`): `except Exception: pass` → `logger.debug(..., exc_info=True)`
- **Graceful error recovery** (`core.py`): `_executor.execute()` обёрнут в try/except, ошибки возвращаются LLM как `[ERROR] ...`
- **mcp зафиксирован** (`requirements.txt`): `mcp>=1.0.0` → `mcp==1.26.0`
- 4 новых теста: `test_retry_on_rate_limit`, `test_no_retry_on_auth_error`, `test_call_tool_timeout` + расширение существующих

## [2026-03-10] — Блок 8: CDP по умолчанию + Real-Time браузер

- **CDP как режим по умолчанию** (`config.py`): поле `cdp_endpoint` с дефолтом `http://localhost:9222`, значение `none` → автономный режим
- **main.py**: формирование MCP args с `--cdp-endpoint`, информативные сообщения о режиме, подсказка при ошибке подключения к CDP
- **.env.example**: добавлена секция CDP с комментариями
- **README.md**: новая секция «Подключение к открытому браузеру», обновлена таблица конфигурации
- 4 новых теста: `test_cdp_endpoint_default`, `test_cdp_endpoint_none`, `test_cdp_endpoint_none_case_insensitive`, `test_cdp_endpoint_custom`

## [2026-03-10] — Блок 7: Критические баги

- **BUG-1** (`context.py`): `build_messages()` теперь группирует tool_use из одного LLM-ответа в одно assistant message, а tool_result — в одно user message (поле `group_id` в `Step`)
- **BUG-2** (`core.py`, `context.py`): текстовые ответы LLM (без tool calls) записываются в контекст через `add_text_response()`, не теряются и не нарушают чередование user/assistant
- **BUG-3** (`core.py`): `input()` заменён на `await asyncio.to_thread(input, ...)` — event loop больше не блокируется при ожидании ввода пользователя
- 4 новых теста: группировка tool_use, смешанные группы, текстовый ответ в контексте, текстовый ответ между tool calls

## [2026-03-09] — Блок 6: Оптимизация и полировка

- **Prompt caching** в `llm_client.py`: system prompt и последний tool с `cache_control: ephemeral`, отслеживание `cache_creation_input_tokens` и `cache_read_input_tokens` в `LLMResponse`
- **Сжатие контекста** в `context.py`: метод `compress_old_steps(llm_client, keep_recent=10)` — суммаризация старых шагов через LLM; вызов из `core.py` при `estimate_tokens() > 30000`
- **Сохранение сессии браузера**: `BROWSER_STORAGE_PATH` в config, передача `--save-storage`/`--storage-state` в MCP-сервер
- **README.md**: описание проекта, установка, использование, конфигурация, архитектура
- Добавлен `browser_state.json` в `.gitignore`
- 51 тест проходит (блоки 1–6)

## [2026-03-09] — Блок 5: CLI интерфейс (main.py)

- Создан `main.py` — CLI точка входа: load_config → Memory → MCPClient.start → merge_tools → AgentLoop.run
- CLI-команды: ввод задачи, `memory`/`память` для просмотра памяти, `quit`/`exit`/`выход` для завершения
- Каждая задача создаёт свой ContextManager + AgentLoop
- Graceful shutdown: MCP-сервер корректно останавливается в finally
- 49 тестов проходят (блоки 1–5)

## [2026-03-09] — Блок 4: Персистентная память

- Написаны тесты `tests/test_memory.py` (8 шт.): save/load, has/delete, list_keys, persistence между рестартами, загрузка env defaults, защита от перезаписи
- `agent/memory.py` уже был реализован в блоке 2 — все 8 тестов прошли сразу
- Итого: 49 тестов проходят (блоки 1+2+3+4)

## [2026-03-09] — Блок 3: Ядро агента — context, prompts, core

- Создан `agent/context.py` — `ContextManager` + `Step`: история шагов, build_messages() в формате Anthropic (goal → tool_use/tool_result пары), оценка токенов, суммаризация
- Создан `agent/prompts.py` — системный промпт для ReAct-агента с описанием MCP и кастомных tools, `build_system_prompt(config)` с инъекцией конфигурации
- Создан `agent/core.py` — `AgentLoop.run()`: ReAct-цикл (LLM → tool call → result → repeat), обработка done/ask_user/confirm/show_preview, audit log в agent_log.jsonl
- Написаны тесты: 9 для context, 7 для core — все 41 тест проходят (блоки 1+2+3)

## [2026-03-09] — Блок 2: LLM-клиент, инструменты и исполнитель

- Создан `agent/tools.py` — 6 кастомных tools (remember, recall, ask_user, show_preview, confirm, done) в формате Anthropic + `merge_tools()` для объединения с MCP tools
- Создан `agent/llm_client.py` — обёртка Anthropic API: `LLMClient.send_message()`, парсинг text/thinking/tool_use блоков, dataclass `ToolCall` и `LLMResponse`
- Создан `agent/tool_executor.py` — роутер tool calls: MCP tools → `mcp_client.call_tool()`, remember/recall → `Memory`, unknown → сообщение об ошибке
- Создан `agent/memory.py` — персистентное key-value хранилище (JSON файл), поддержка env defaults
- Написаны тесты: 6 для tools, 5 для llm_client, 5 для tool_executor — все 25 тестов проходят

## [2026-03-09] — Блок 1: Фундамент — config, mcp_client

- Создан `requirements.txt` с зависимостями: anthropic, python-dotenv, pytest, pytest-asyncio, mcp
- Создан `.env.example` с описанием всех переменных окружения
- Создан `agent/config.py` — загрузка `.env` → dataclass `Config` с дефолтами и валидацией
- Создан `agent/mcp_client.py` — обёртка MCP SDK: `start()`, `stop()`, `list_tools()`, `call_tool()`, async context manager
- Конвертация MCP tools в формат Anthropic (`name`, `description`, `input_schema`)
- Извлечение текста из `CallToolResult` (поддержка нескольких `TextContent` блоков)
- Создан `tests/conftest.py` с изоляцией `.env` (autouse fixture)
- Написаны тесты: 4 для config, 5 для mcp_client — все проходят

## [2026-03-09] — Настройка MCP-сервера в VS Code

- Создан `.vscode/mcp.json` с конфигурацией Playwright MCP-сервера (`@playwright/mcp`)
- Сервер запускается через `npx -y @playwright/mcp@latest` (stdio)
- Конфигурация следует официальной документации VS Code: https://code.visualstudio.com/docs/copilot/customization/mcp-servers

## [2026-03-09] — Переход на Microsoft Playwright MCP

- Полностью переписан `PLAN.md` под архитектуру с MCP-сервером (`@playwright/mcp`)
- Удалены модули `browser.py`, `page_observer.py` (заменены внешним MCP-сервером)
- Добавлен `mcp_client.py` — подключение к MCP, конвертация tools, call_tool
- Browser tools (~20 шт.) приходят от MCP автоматически: hover, go_back/forward, handle_dialog, file_upload, tab management
- Кастомных tools сокращено до 6: remember, recall, ask_user, show_preview, confirm, done
- `tool_executor.py` упрощён до роутера: MCP tools → mcp_client, кастомные → локально
- Добавлены архитектурные идеи из анализа MCP-серверов: audit log, browser state persistence, plan-before-act в промпте
- Объём плана сокращён ~3x: убраны полные листинги тестов, оставлены интерфейсы и списки тест-кейсов

## [2026-03-09] — Создание плана проекта

- Создан `PLAN.md` — детальный план разработки AI Browser Agent по 6 блокам
- План включает: TDD-шаги, примеры тестов, требования к реализации каждого модуля
- Структура позволяет итеративную разработку: «начинай блок N» → агент читает план → выполняет
