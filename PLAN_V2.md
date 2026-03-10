# PLAN V2 — Исправления и фичи

> **На основе:** [ANALYSIS.md](ANALYSIS.md)  
> **Дата:** 2026-03-10  
> **Как использовать:** Скажи «Начинай блок N» — агент прочтёт план и выполнит.

---

## Ключевое требование: CDP по умолчанию

Агент **по умолчанию** подключается к уже открытому браузеру через CDP (Chrome DevTools Protocol).  
Пользователь запускает Chrome вручную → видит все действия агента **в реальном времени**.

**Порядок запуска:**
```bash
# 1. Пользователь запускает Chrome с удалённой отладкой:
chrome.exe --remote-debugging-port=9222

# 2. Запуск агента (подключается к открытому Chrome):
python main.py
```

Если `CDP_ENDPOINT` не задан — берётся `http://localhost:9222` по умолчанию.  
Если `CDP_ENDPOINT=none` — старое поведение (MCP запускает свой браузер).

---

## Зависимости между блоками

```
БЛОК 7: Критические баги (BUG-1, BUG-2, BUG-3)
   ↓
БЛОК 8: CDP по умолчанию + real-time браузер
   ↓
БЛОК 9: Надёжность (retry, таймауты, logging)
   ↓
БЛОК 10: Оптимизация токенов (OPT-1..5)
   ↓
БЛОК 11: Фичи (smart retry, трекер токенов, dry-run)
   ↓
БЛОК 12: UX + полировка (пресеты, валидация, CI)
```

---

# БЛОК 7: Критические баги

**Цель:** Исправить 3 бага, из-за которых агент ломается в runtime.

**Файлы:** `agent/context.py`, `agent/core.py`

**Правило:** Тесты НЕ модифицируются. Только исходный код.

---

### Шаг 7.1: BUG-1 — Множественные tool_use в одном сообщении

**Файл:** `agent/context.py` → `build_messages()`, `agent/core.py` → `run()`

**Проблема:** Каждый tool_call → отдельная пара assistant/user. Anthropic API требует, чтобы все tool_use из одного ответа LLM были в **одном** assistant message.

**Что менять:**

1. В `context.py` — изменить `Step` и `build_messages()`:
   - `Step` получает поле `group_id: str | None` — идентификатор группы (один LLM response = одна группа)
   - `build_messages()` группирует шаги с одинаковым `group_id` в одно assistant + одно user сообщение
   - Шаги без `group_id` (legacy) — по-прежнему каждый отдельно

2. В `core.py` — в `run()`:
   - Генерировать `group_id` для каждого LLM response (напр. `f"resp_{step_num}"`)
   - Передавать `group_id` в каждый `Step` из этого response

**Тесты:** Существующие тесты должны пройти. Написать новые:
- `test_multiple_tool_calls_single_message` — 2 tool_use → 1 assistant msg + 1 user msg
- `test_mixed_groups` — шаги из разных ответов → разные message-группы

- [ ] Тест → код → `pytest -v` ✅

---

### Шаг 7.2: BUG-2 — Text-only response теряется

**Файл:** `agent/core.py` → `run()`

**Проблема:** Когда LLM возвращает текст без tools:
```python
if not response.tool_calls:
    logger.info("LLM text response (no tools): %s", response.text)
    continue  # ← текст потерян, нарушена очередность user/assistant
```

**Что менять:**
- Вместо `continue` — добавить текстовый ответ в контекст
- В `context.py` добавить метод `add_text_response(text: str)` → записывает assistant message с text content
- В `build_messages()` — рендерить текстовые ответы как `{"role": "assistant", "content": text}`
- После текстового ответа нужен следующий user message (закономерно придёт при следующем шаге)

**Тесты:**
- `test_text_response_in_context` — текст появляется в build_messages()
- Существующий `test_returns_summary_on_done` продолжает проходить

- [ ] Тест → код → `pytest -v` ✅

---

### Шаг 7.3: BUG-3 — Блокирующий input()

**Файл:** `agent/core.py` → `_handle_tool_call()`

**Проблема:** `input()` блокирует event loop — MCP heartbeat, таймауты и все корутины замирают.

**Что менять:**
```python
# Было:
result = input("> ")

# Стало:
result = await asyncio.to_thread(input, "> ")
```

Заменить **все** вызовы `input()` в `_handle_tool_call()` на `await asyncio.to_thread(input, ...)`.

**Тесты:** Существующие тесты мокают `input` — должны пройти без изменений.

- [ ] Код → `pytest -v` ✅

---

### Шаг 7.4: Финальная проверка блока 7

- [ ] `python -m pytest -v` → все тесты зелёные
- [ ] CHANGELOG.md

---

# БЛОК 8: CDP по умолчанию + Real-Time браузер

**Цель:** Агент по умолчанию подключается к уже открытому Chrome. Пользователь видит действия в реальном времени.

**Файлы:** `agent/config.py`, `agent/mcp_client.py`, `main.py`, `.env.example`

---

### Шаг 8.1: Config — добавить CDP_ENDPOINT

**Файл:** `agent/config.py`

**Что менять:**
- Добавить поле `cdp_endpoint: str = "http://localhost:9222"` в `Config`
- `load_config()` читает `CDP_ENDPOINT` из env
- Значение `"none"` (case-insensitive) → пустая строка (= запуск своего браузера)
- По умолчанию = `http://localhost:9222`

**Файл:** `.env.example`
- Добавить `CDP_ENDPOINT=http://localhost:9222` с комментарием

**Тесты:**
- `test_cdp_endpoint_default` — по умолчанию `http://localhost:9222`
- `test_cdp_endpoint_none` — `CDP_ENDPOINT=none` → `""`
- `test_cdp_endpoint_custom` — пользовательское значение берётся

- [ ] Тест → код → `pytest tests/test_config.py -v` ✅

---

### Шаг 8.2: MCPClient — поддержка CDP args

**Файл:** `agent/mcp_client.py`

**Что менять — ничего в самом MCPClient.** CDP передаётся через аргументы MCP-сервера:
```
npx @playwright/mcp --cdp-endpoint=http://localhost:9222
```

Логика формирования args — в `main.py` (шаг 8.3).

---

### Шаг 8.3: main.py — CDP как режим по умолчанию

**Файл:** `main.py`

**Что менять в формировании `mcp_args`:**

```python
mcp_args = [config.mcp_browser_args]

# CDP — по умолчанию подключаемся к уже открытому браузеру
if config.cdp_endpoint:
    mcp_args.append(f"--cdp-endpoint={config.cdp_endpoint}")
else:
    # Стандартный режим: MCP запускает свой браузер
    if config.browser_headless:
        mcp_args.append("--headless")
    mcp_args.append(f"--viewport-size={config.browser_viewport_width},{config.browser_viewport_height}")
    if config.browser_storage_path:
        storage = config.browser_storage_path
        if os.path.exists(storage):
            mcp_args.append(f"--storage-state={storage}")
        mcp_args.append(f"--save-storage={storage}")

# Информируем пользователя о режиме
if config.cdp_endpoint:
    print(f"🌐 Режим: подключение к открытому браузеру ({config.cdp_endpoint})")
    print(f"   Убедитесь, что Chrome запущен с --remote-debugging-port=9222")
else:
    print(f"🌐 Режим: MCP запускает свой браузер (headless={config.browser_headless})")
```

**Тесты:** Ручная проверка:
- [ ] `CDP_ENDPOINT=http://localhost:9222 python main.py` → подключается к открытому Chrome
- [ ] `CDP_ENDPOINT=none python main.py` → MCP запускает свой браузер

---

### Шаг 8.4: Документация запуска

**Файл:** `README.md` — добавить секцию «Режим работы с открытым браузером»:

```markdown
## Подключение к открытому браузеру (по умолчанию)

1. Запустите Chrome с удалённой отладкой:
   ```bash
   # Windows
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
   
   # macOS
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
   
   # Linux
   google-chrome --remote-debugging-port=9222
   ```

2. Запустите агента:
   ```bash
   python main.py
   ```

Агент подключится к вашему Chrome и вы увидите все действия в реальном времени.

Для автономного режима (MCP запускает свой браузер):
```env
CDP_ENDPOINT=none
```
```

- [ ] README обновлён

---

### Шаг 8.5: Финальная проверка блока 8

- [ ] `python -m pytest -v` → все тесты зелёные
- [ ] CHANGELOG.md

---

# БЛОК 9: Надёжность

**Цель:** Retry, таймауты, logging — агент не падает при временных ошибках.

**Файлы:** `agent/llm_client.py`, `agent/mcp_client.py`, `agent/core.py`, `main.py`, `requirements.txt`

---

### Шаг 9.1: Retry с backoff для Anthropic API

**Файл:** `agent/llm_client.py` → `send_message()`

**Что менять:**
- Обернуть `self._client.messages.create()` в retry-цикл (3 попытки)
- Exponential backoff: 1s → 2s → 4s
- Retry только на 429, 500, 529, `APIConnectionError`
- 400/401/403 — не ретраить, пробрасывать

```python
import time

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # секунды

for attempt in range(MAX_RETRIES):
    try:
        response = await asyncio.to_thread(self._client.messages.create, ...)
        return self._parse_response(response)
    except anthropic.RateLimitError:
        if attempt == MAX_RETRIES - 1:
            raise
        await asyncio.sleep(RETRY_DELAYS[attempt])
    except anthropic.InternalServerError:
        if attempt == MAX_RETRIES - 1:
            raise
        await asyncio.sleep(RETRY_DELAYS[attempt])
```

**Тесты:**
- `test_retry_on_rate_limit` — мок 429 → 429 → 200, result ok
- `test_no_retry_on_auth_error` — 401 → сразу raise

- [ ] Тест → код → `pytest tests/test_llm_client.py -v` ✅

---

### Шаг 9.2: Таймаут на MCP call_tool

**Файл:** `agent/mcp_client.py` → `call_tool()`

**Что менять:**
```python
async def call_tool(self, name: str, arguments: dict, timeout: float = 60.0) -> str:
    if self._session is None:
        raise RuntimeError("MCPClient not started")
    result = await asyncio.wait_for(
        self._session.call_tool(name, arguments),
        timeout=timeout,
    )
    return self._extract_text(result)
```

Добавить `import asyncio` в начало файла.

**Тесты:**
- `test_call_tool_timeout` — мок зависает → `asyncio.TimeoutError` через 0.1s

- [ ] Тест → код → `pytest tests/test_mcp_client.py -v` ✅

---

### Шаг 9.3: Logging — настройка базовой конфигурации

**Файл:** `main.py` (в начале `main()`)

**Что менять:**
```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
```

**Файл:** `agent/mcp_client.py` → `stop()` — заменить `except Exception: pass` на logging:
```python
except Exception:
    logger.debug("Error closing MCP session", exc_info=True)
```

- [ ] Код → `pytest -v` ✅

---

### Шаг 9.4: Graceful error recovery в tool execution

**Файл:** `agent/core.py` → `_handle_tool_call()`

**Что менять:** Ошибки в tool call не должны крашить агент. Вернуть ошибку как текст для LLM:
```python
case _:
    try:
        result = await self._executor.execute(tc)
    except Exception as e:
        result = f"Tool error: {e}"
        logger.warning("Tool %s failed: %s", tc.name, e)
```

(ToolExecutor уже ловит ошибки, но внешний слой в core.py — нет)

- [ ] Код → `pytest -v` ✅

---

### Шаг 9.5: Зафиксировать mcp версию

**Файл:** `requirements.txt`

**Что менять:** `mcp>=1.0.0` → `mcp==1.8.1` (или текущая установленная версия).

- [ ] `pip show mcp` → узнать точную версию → зафиксировать

---

### Шаг 9.6: Финальная проверка блока 9

- [ ] `python -m pytest -v` → все тесты зелёные
- [ ] CHANGELOG.md

---

# БЛОК 10: Оптимизация токенов

**Цель:** Сократить расход на 40-60% на длинных задачах без потери качества.

**Файлы:** `agent/context.py`, `agent/core.py`, `agent/prompts.py`, `agent/tool_executor.py`

---

### Шаг 10.1: OPT-1 — Убрать thinking из контекста

**Файл:** `agent/context.py` → `build_messages()`

**Что менять:**
- В `build_messages()` **НЕ** добавлять `step.thinking` в assistant content
- Thinking остаётся в `Step` (для audit log), но не в messages
- В `estimate_tokens()` — тоже не считать thinking

```python
# Было:
if step.thinking:
    assistant_content.append({"type": "text", "text": step.thinking})

# Стало: (удалить эти 2 строки)
```

**Тесты:** Существующие должны пройти (если тесты проверяли thinking в messages — добавить новые/скорректировать подход).

- [ ] Код → `pytest -v` ✅

---

### Шаг 10.2: OPT-3 — Локальная суммаризация вместо LLM

**Файл:** `agent/context.py` → `compress_old_steps()`

**Что менять:** Заменить LLM-вызов на детерминированное сжатие:
```python
async def compress_old_steps(self, llm_client: LLMClient | None = None, keep_recent: int = 7) -> None:
    if len(self._steps) <= keep_recent:
        return

    old_steps = self._steps[:-keep_recent]
    recent_steps = self._steps[-keep_recent:]

    summary_lines = []
    if self._summary:
        summary_lines.append(self._summary)
    for i, s in enumerate(old_steps, 1):
        result_preview = (s.result or "")[:100].replace("\n", " ")
        summary_lines.append(f"Step {i}: {s.action} → {result_preview}")

    self._summary = "\n".join(summary_lines)
    self._steps = recent_steps
```

**Бонус:** Убирается зависимость от `llm_client` в сжатии → экономия 1 API call.

**Тесты:** Обновить ожидания — сжатие теперь не требует LLM.

- [ ] Код → `pytest -v` ✅

---

### Шаг 10.3: OPT-5 — Порог сжатия 15000 вместо 30000

**Файл:** `agent/core.py` → `run()`

**Что менять:**
```python
# Было:
if self._context.estimate_tokens() > 30000:

# Стало:
if self._context.estimate_tokens() > 15000:
```

- [ ] Код → `pytest -v` ✅

---

### Шаг 10.4: OPT-2 — Обрезка snapshot от browser_snapshot

**Файл:** `agent/tool_executor.py`

**Что менять:** Добавить постобработку результата `browser_snapshot`:
```python
MAX_SNAPSHOT_CHARS = 8000

async def execute(self, tool_call: ToolCall) -> str:
    ...
    if tool_call.name in self._mcp_tool_names:
        result = await self._mcp.call_tool(tool_call.name, tool_call.args)
        if tool_call.name == "browser_snapshot" and len(result) > MAX_SNAPSHOT_CHARS:
            result = self._truncate_snapshot(result)
        return result
    ...

@staticmethod
def _truncate_snapshot(text: str, max_chars: int = 8000) -> str:
    """Truncate long a11y snapshots, keeping structure."""
    lines = text.split("\n")
    output = []
    total = 0
    for line in lines:
        total += len(line) + 1
        if total > max_chars:
            output.append(f"... ({len(lines) - len(output)} more lines truncated)")
            break
        output.append(line)
    return "\n".join(output)
```

**Тесты:**
- `test_truncate_snapshot_short` — текст < 8000 → без изменений
- `test_truncate_snapshot_long` — текст > 8000 → обрезан, есть "truncated"

- [ ] Тест → код → `pytest tests/test_tool_executor.py -v` ✅

---

### Шаг 10.5: OPT-4 — Убрать дубли tools из system prompt

**Файл:** `agent/prompts.py`

**Что менять:** Убрать секции `## Browser Tools (from MCP)` и `## Custom Tools` из `SYSTEM_PROMPT`. Оставить только правила поведения. Описания tools уже в JSON-схемах (параметр `tools`).

Новый prompt (~экономия 300 tokens):
```python
SYSTEM_PROMPT = """You are an autonomous AI agent controlling a web browser via MCP tools.

## How You Work
1. Observe page: browser_snapshot → see structure with [ref] markers
2. Think about next action
3. Take ONE action via a tool
4. Observe result, repeat

## Important Rules
1. ALWAYS start with browser_snapshot to see the page
2. Use ref="..." from snapshot to identify elements — NEVER guess
3. Before destructive actions — ALWAYS confirm()
4. For user data — recall() first, ask_user() if not found
5. Save discoveries with remember()
6. Plan 2-3 steps ahead before acting
7. ONE action at a time, then observe
8. When done — call done() with summary
9. NEVER guess URLs — only use visible links or user-provided URLs
10. If a new tab opens unexpectedly — use browser_tab_list to check

## Language
- Think in English, communicate with user in Russian
"""
```

- [ ] Код → `pytest -v` ✅

---

### Шаг 10.6: Финальная проверка блока 10

- [ ] `python -m pytest -v` → все тесты зелёные
- [ ] CHANGELOG.md

---

# БЛОК 11: Фичи

**Цель:** Полезные фичи из ANALYSIS.md — smart retry, трекер токенов, dry-run.

**Файлы:** `agent/core.py`, `agent/tool_executor.py`, `main.py`, `agent/prompts.py`

---

### Шаг 11.1: FEAT-1 — Smart Retry с is_error

**Файл:** `agent/tool_executor.py` → `execute()`, `agent/core.py`

**Что менять:**
- `execute()` при ошибке MCP возвращает строку с префиксом `"[ERROR] "` 
- В `core.py` при добавлении Step — проверять result на `[ERROR]` и логировать
- LLM увидит ошибку и скорректируется (snapshot → повторить action)

```python
# tool_executor.py:
except Exception as e:
    return f"[ERROR] {e}"
```

Это уже почти так. Нужно прокинуть `is_error` в tool_result:
```python
# context.py → build_messages():
tool_result = {
    "type": "tool_result",
    "tool_use_id": tool_call_id,
    "content": step.result or "",
}
if step.is_error:
    tool_result["is_error"] = True
```

**Тесты:**
- `test_error_result_has_is_error_flag` — ошибочный step → `is_error: true` в messages

- [ ] Тест → код → `pytest -v` ✅

---

### Шаг 11.2: FEAT-2 — Трекер расхода токенов

**Файл:** `agent/core.py`, `main.py`

**Что менять в core.py:**
- Добавить в `AgentLoop` аккумуляторы: `_total_input_tokens`, `_total_output_tokens`
- После каждого LLM call: `self._total_input_tokens += response.input_tokens`
- Метод `get_usage() -> dict` возвращает статистику
- `run()` возвращает summary, а usage доступен через `agent.get_usage()`

**Что менять в main.py:**
- После `agent.run()` — вывести:
```python
usage = agent.get_usage()
print(f"📊 [{usage['steps']} шагов, {usage['input_tokens']//1000}K input, {usage['output_tokens']//1000}K output]")
```

**Тесты:**
- `test_usage_tracking` — после run → get_usage() содержит steps, input_tokens, output_tokens

- [ ] Тест → код → `pytest -v` ✅

---

### Шаг 11.3: FEAT-3 — Режим dry-run

**Файл:** `agent/core.py`, `agent/prompts.py`, `main.py`

**Что менять:**

В `prompts.py` — новый промпт для планирования:
```python
PLAN_PROMPT = """Analyze the task and create a step-by-step plan (5-10 steps).
Do NOT execute — only plan. Use available tool names.
Format:
1. tool_name: description
2. tool_name: description
...
"""
```

В `core.py` — метод `plan(task: str) -> str`:
- Один LLM call с `PLAN_PROMPT` + system prompt
- Возвращает текст плана

В `main.py`:
- Если ввод начинается с `plan ` → вызвать `agent.plan(task)` → показать план
- Пользователь пишет `go` → выполнить

**Тесты:**
- `test_plan_returns_text` — plan() → непустой текст, без tool calls

- [ ] Тест → код → `pytest -v` ✅

---

### Шаг 11.4: Финальная проверка блока 11

- [ ] `python -m pytest -v` → все тесты зелёные
- [ ] CHANGELOG.md

---

# БЛОК 12: UX + полировка

**Цель:** Мелкие улучшения для удобства и безопасности.

**Файлы:** `agent/config.py`, `agent/memory.py`, `main.py`, `requirements.txt`

---

### Шаг 12.1: BUG-6 — Валидация числовых env

**Файл:** `agent/config.py`

**Что менять:** Обернуть `int()` вызовы:
```python
def _parse_int(value: str, name: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be an integer, got: {value!r}")
```

- [ ] Код → `pytest tests/test_config.py -v` ✅

---

### Шаг 12.2: BUG-5 — Логирование ошибок в MCP stop()

**Файл:** `agent/mcp_client.py` → `stop()`

**Что менять:**
```python
except Exception:
    logger.debug("Error closing MCP session", exc_info=True)
```

- [ ] Код → `pytest -v` ✅

---

### Шаг 12.3: Signal handling в main.py

**Файл:** `main.py`

**Что менять:** Ctrl+C при выполнении задачи → корректная остановка MCP:
```python
import signal

# В main():
loop = asyncio.get_event_loop()
for sig in (signal.SIGINT, signal.SIGTERM):
    loop.add_signal_handler(sig, ...)
```

На Windows `add_signal_handler` не работает. Использовать try/except KeyboardInterrupt (уже есть частично).

**Убедиться:**
- Ctrl+C во время `agent.run()` → MCP stop() вызывается (finally блок)
- Ctrl+C во время `input()` → выход из CLI loop

- [ ] Ручная проверка

---

### Шаг 12.4: CLI — подсказка о запуске Chrome

**Файл:** `main.py`

**Что менять:** Если CDP режим и MCP не смог подключиться — вывести понятную ошибку:
```python
try:
    await mcp.start(config.mcp_browser_command, mcp_args)
except Exception as exc:
    if config.cdp_endpoint:
        print(f"❌ Не удалось подключиться к браузеру ({config.cdp_endpoint}).")
        print(f"   Запустите Chrome: chrome.exe --remote-debugging-port=9222")
    else:
        print(f"❌ Не удалось запустить MCP-сервер: {exc}")
    sys.exit(1)
```

- [ ] Код → `pytest -v` ✅

---

### Шаг 12.5: Финальная проверка блока 12

- [ ] `python -m pytest -v` → все тесты зелёные
- [ ] CHANGELOG.md

---

# Итого: последовательность действий

| # | Блок | Задачи | Сложность |
|---|---|---|---|
| 7 | Критические баги | BUG-1, BUG-2, BUG-3 | Medium |
| 8 | CDP по умолчанию | Config, main.py, README | Low |
| 9 | Надёжность | Retry, таймауты, logging, mcp version | Medium |
| 10 | Оптимизация токенов | OPT-1..5 — убрать thinking, локальное сжатие, обрезка snapshot | Medium |
| 11 | Фичи | Smart retry, трекер токенов, dry-run | Medium |
| 12 | UX + полировка | Валидация, logging MCP, signals, CLI подсказки | Low |

**Общая оценка:** ~6 блоков, каждый — «начинай блок N».
