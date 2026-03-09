# PLAN.md — AI Browser Agent (MCP Edition)

> **Как пользоваться этим планом:**
> 1. Скажи агенту: _«Начинай делать блок N»_
> 2. Агент читает PLAN.md + CHANGELOG.md для контекста
> 3. Идёт по шагам блока (TDD: сначала тест → потом код)
> 4. Запускает `python -m pytest` после каждого модуля
> 5. После завершения блока: ставит `[x]`, пишет в CHANGELOG.md

---

## О проекте

**Что строим:** Универсальный AI-агент, который получает текстовую задачу и **сам** выполняет её в веб-браузере. Никакого хардкода шагов, селекторов или URL.

**Стек:** Python 3.13 · **Microsoft Playwright MCP** (управление браузером) · Anthropic Claude Sonnet · MCP SDK · python-dotenv · pytest

**Паттерн:** ReAct (observe → think → act).

**Архитектурное решение:** Браузером управляет внешний MCP-сервер (`@playwright/mcp`). Наш код — LLM-логика, контекст, память и ReAct-цикл. Browser tools приходят от MCP автоматически.

**Жёсткие запреты:**
- ❌ Заготовленные шаги для конкретных задач
- ❌ Преднаписанные CSS-селекторы
- ❌ Захардкоженные URL/подсказки по элементам

---

## Что даёт MCP-сервер «из коробки»

~20 browser tools (автоматически доступны агенту через `list_tools()`):

| Группа | Tools |
|---|---|
| Навигация | `browser_navigate`, `browser_go_back`, `browser_go_forward` |
| Взаимодействие | `browser_click`, `browser_hover`, `browser_drag`, `browser_type`, `browser_select_option`, `browser_press_key` |
| Наблюдение | `browser_snapshot` (a11y tree с ref'ами), `browser_take_screenshot` |
| Вкладки | `browser_tab_list`, `browser_tab_new`, `browser_tab_select`, `browser_tab_close` |
| Прочее | `browser_wait`, `browser_resize`, `browser_handle_dialog`, `browser_file_upload` |

**Идентификация элементов:** через `ref`-атрибуты из a11y snapshot (НЕ CSS-селекторы).

---

## Наши кастомные tools (6 шт.)

| Tool | Параметры | Описание |
|---|---|---|
| `remember` | `key: str, value: str` | Save info to persistent memory |
| `recall` | `key: str` | Retrieve info from memory |
| `ask_user` | `question: str` | Ask user for information |
| `show_preview` | `title: str, items: list[str]` | Show preview list to user |
| `confirm` | `question: str` | Yes/no confirmation before destructive actions |
| `done` | `summary: str` | Task completed — report results |

---

## Целевая структура файлов

```
MyAgent/
├── main.py                     # CLI: ввод задачи → агент → результат
├── agent/
│   ├── __init__.py
│   ├── config.py               # .env → dataclass Config
│   ├── mcp_client.py           # Подключение к Playwright MCP-серверу
│   ├── tools.py                # Кастомные tools (6 шт.) + мерж с MCP tools
│   ├── llm_client.py           # Anthropic API обёртка
│   ├── tool_executor.py        # Роутер: MCP tools → mcp_client, кастомные → локально
│   ├── context.py              # История шагов, сжатие, лимиты токенов
│   ├── memory.py               # Персистентная key-value память
│   ├── prompts.py              # Системный промпт
│   └── core.py                 # AgentLoop — ReAct-цикл
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_mcp_client.py
│   ├── test_tools.py
│   ├── test_llm_client.py
│   ├── test_tool_executor.py
│   ├── test_context.py
│   ├── test_memory.py
│   └── test_core.py
├── memory.json
├── .env
├── .env.example
├── requirements.txt
├── PLAN.md
├── CHANGELOG.md
└── README.md
```

---

## Зависимости между блоками

```
БЛОК 1 (config, mcp_client)
   ↓
БЛОК 2 (tools, llm_client, tool_executor)  ←  БЛОК 4 (memory) — параллельно
   ↓
БЛОК 3 (context, prompts, core)
   ↓
БЛОК 5 (main.py — CLI)
   ↓
БЛОК 6 (оптимизация, реальные сценарии)
```

---

## .env — структура переменных

```env
# === LLM ===
ANTHROPIC_API_KEY=sk-ant-...
LLM_MODEL=claude-sonnet-4-20250514
LLM_MAX_TOKENS=4096

# === Агент ===
MAX_AGENT_STEPS=50
SCREENSHOT_ENABLED=true

# === MCP Browser ===
MCP_BROWSER_COMMAND=npx
MCP_BROWSER_ARGS=@playwright/mcp
BROWSER_HEADLESS=false
BROWSER_VIEWPORT_WIDTH=1280
BROWSER_VIEWPORT_HEIGHT=900

# === Лимиты ===
MAX_EMAILS_TO_SCAN=20
MAX_VACANCIES=5

# === Данные пользователя ===
USER_FULL_NAME=
USER_PHONE=
USER_EMAIL=
DELIVERY_ADDRESS=
```

---

# БЛОКИ РЕАЛИЗАЦИИ

---

## БЛОК 1: Фундамент — config, mcp_client

**Цель:** Загрузка конфигурации + подключение к Playwright MCP-серверу.

**Файлы:** `requirements.txt`, `.env.example`, `agent/__init__.py`, `agent/config.py`, `agent/mcp_client.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/test_config.py`, `tests/test_mcp_client.py`

---

### Шаг 1.1: Инфраструктура

- [x] Создать `requirements.txt`:
```
anthropic==0.52.0
python-dotenv==1.1.0
pytest==8.3.4
pytest-asyncio==0.25.3
mcp>=1.0.0
```
- [x] Установить: `pip install -r requirements.txt`
- [x] Установить MCP-сервер: `npm install -g @playwright/mcp` (требуется Node.js)
- [x] Создать `.env.example`, `agent/__init__.py`, `tests/__init__.py`
- [x] Проверить: `python -c "import anthropic; import mcp; print('OK')"`

---

### Шаг 1.2: config.py (TDD)

**Что делает:** Загружает .env → dataclass Config.

**Интерфейс:**
```python
@dataclass
class Config:
    anthropic_api_key: str
    llm_model: str              # default: "claude-sonnet-4-20250514"
    llm_max_tokens: int         # default: 4096
    max_agent_steps: int        # default: 50
    screenshot_enabled: bool    # default: True
    mcp_browser_command: str    # default: "npx"
    mcp_browser_args: str       # default: "@playwright/mcp"
    browser_headless: bool      # default: False
    browser_viewport_width: int # default: 1280
    browser_viewport_height: int # default: 900
    max_emails_to_scan: int     # default: 20
    max_vacancies: int          # default: 5

def load_config() -> Config: ...
```

**Тесты** (`tests/test_config.py`):
- `test_loads_api_key` — ключ загружается из env
- `test_missing_api_key_raises` — ValueError без ключа
- `test_default_values` — дефолты для всех полей (включая mcp_browser_command, mcp_browser_args)
- `test_custom_values_from_env` — env перезаписывает дефолты

**Реализация:**
- `load_dotenv()` + `os.environ`
- Пустой `ANTHROPIC_API_KEY` → `raise ValueError`
- Типы: `"true"/"false"` → bool, числа → int

- [x] Тест → код → `pytest tests/test_config.py -v` ✅

---

### Шаг 1.3: mcp_client.py (TDD)

**Что делает:** Управляет lifecycle MCP-сервера, предоставляет `list_tools()` и `call_tool()`.

**Интерфейс:**
```python
class MCPClient:
    async def start(self, command: str, args: list[str]) -> None
    async def stop(self) -> None
    async def list_tools(self) -> list[dict]              # JSON-схемы в формате Anthropic
    async def call_tool(self, name: str, arguments: dict) -> str
    async def __aenter__(self) -> "MCPClient"
    async def __aexit__(self, *exc) -> None
```

**Ключевой паттерн подключения к MCP:**
```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(command="npx", args=["@playwright/mcp", "--headless"])
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("browser_navigate", {"url": "https://..."})
```

**Тесты** (`tests/test_mcp_client.py`):
- `test_start_and_stop` — запускает и останавливает без ошибок
- `test_context_manager` — работает как async context manager
- `test_list_tools_returns_anthropic_format` — tools имеют `name`, `description`, `input_schema`
- `test_call_tool_returns_string` — результат вызова — строка
- `test_call_nonexistent_tool_raises` — ошибка на несуществующий tool

**Реализация:**
- `start()`: запускает MCP-сервер через `stdio_client`, создаёт `ClientSession`, вызывает `initialize()`
- `list_tools()`: вызывает `session.list_tools()`, конвертирует в формат Anthropic tool_use
- `call_tool()`: вызывает `session.call_tool()`, извлекает текст из результата
- `stop()`: закрывает сессию и транспорт
- Headless/viewport передаются как args: `["@playwright/mcp", "--headless", "--viewport-size=1280,900"]`

**⚠️ Конвертация формата tools (MCP → Anthropic):**
```python
def _convert_tool(self, mcp_tool) -> dict:
    return {
        "name": mcp_tool.name,
        "description": mcp_tool.description or "",
        "input_schema": mcp_tool.inputSchema,
    }
```

- [x] Тест → код → `pytest tests/test_mcp_client.py -v` ✅

---

### Шаг 1.4: Финальная проверка блока 1

- [x] `python -m pytest -v` → все тесты зелёные
- [x] CHANGELOG.md

---

## БЛОК 2: LLM-клиент, инструменты и исполнитель

**Цель:** Claude API + маршрутизация tool calls (MCP vs. локальные).

**Файлы:** `agent/tools.py`, `agent/llm_client.py`, `agent/tool_executor.py` + тесты

---

### Шаг 2.1: tools.py (TDD)

**Что делает:** Определяет 6 кастомных tools + функцию мержа с MCP tools.

**Интерфейс:**
```python
CUSTOM_TOOLS: list[dict]  # 6 кастомных tools в формате Anthropic

def get_custom_tool_names() -> list[str]
def merge_tools(mcp_tools: list[dict]) -> list[dict]  # mcp_tools + CUSTOM_TOOLS
```

**Тесты** (`tests/test_tools.py`):
- `test_custom_tools_have_required_fields` — name, description, input_schema
- `test_no_duplicate_names` — нет дублей в CUSTOM_TOOLS
- `test_custom_tool_count` — ровно 6
- `test_expected_custom_tools_exist` — remember, recall, ask_user, show_preview, confirm, done
- `test_merge_combines_mcp_and_custom` — merge возвращает объединённый список
- `test_merge_no_name_conflicts` — если MCP вернул tool с тем же именем, наш приоритетнее

**Реализация:** 6 JSON-схем. Описания на английском.

- [x] Тест → код → `pytest tests/test_tools.py -v` ✅

---

### Шаг 2.2: llm_client.py (TDD)

**Что делает:** Обёртка Anthropic API — отправляет messages + tools, парсит ответ.

**Интерфейс:**
```python
@dataclass
class ToolCall:
    id: str
    name: str
    args: dict

@dataclass
class LLMResponse:
    text: str | None = None
    thinking: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0

class LLMClient:
    def __init__(self, api_key: str, model: str, max_tokens: int = 4096)
    async def send_message(self, messages: list, system: str, tools: list) -> LLMResponse
    def _parse_response(self, response) -> LLMResponse
```

**Тесты** (`tests/test_llm_client.py`, мокаем Anthropic API):
- `test_parse_text_response` — парсит текстовый ответ (text, без tool_calls)
- `test_parse_tool_response` — парсит tool_use (thinking + ToolCall)
- `test_send_message_calls_api` — проверяет kwargs: model, system, messages
- `test_tool_call_dataclass` — ToolCall.id, .name, .args
- `test_response_defaults` — LLMResponse() → все поля по умолчанию

**Реализация:**
- `_client = anthropic.Anthropic(api_key=...)` (синхронный SDK)
- `send_message`: `asyncio.to_thread(self._client.messages.create, ...)` для async
- `_parse_response`: итерирует `response.content` → text/tool_use блоки
- Токены из `response.usage`

- [x] Тест → код → `pytest tests/test_llm_client.py -v` ✅

---

### Шаг 2.3: tool_executor.py (TDD)

**Что делает:** Роутер — MCP tools → `mcp_client.call_tool()`, кастомные → локальная обработка.

**Интерфейс:**
```python
class ToolExecutor:
    def __init__(self, mcp_client: MCPClient, memory: Memory)
    async def init_mcp_tools(self) -> list[dict]  # вызов list_tools + запоминание имён
    async def execute(self, tool_call: ToolCall) -> str
```

**Тесты** (`tests/test_tool_executor.py`, мокаем mcp_client и memory):
- `test_mcp_tool_routed_to_mcp` — browser_click → mcp_client.call_tool
- `test_remember_saves_to_memory` — remember → memory.save
- `test_recall_existing` — recall → memory.load → значение
- `test_recall_missing` — recall → "not found"
- `test_unknown_tool_returns_error` — fly_to_moon → "unknown tool"

**Реализация:**
```python
async def execute(self, tool_call: ToolCall) -> str:
    try:
        if tool_call.name in self._mcp_tool_names:
            return await self._mcp.call_tool(tool_call.name, tool_call.args)
        match tool_call.name:
            case "remember": ...
            case "recall": ...
            case _: return f"Unknown tool: {tool_call.name}"
    except Exception as e:
        return f"Error: {e}"
```

- [x] Тест → код → `pytest tests/test_tool_executor.py -v` ✅

---

### Шаг 2.4: Финальная проверка блока 2

- [x] `python -m pytest -v` → все тесты зелёные (блоки 1 + 2)
- [x] CHANGELOG.md

---

## БЛОК 3: Ядро агента — context, prompts, core

**Цель:** ReAct-цикл, собирающий всё вместе.

**Файлы:** `agent/context.py`, `agent/prompts.py`, `agent/core.py` + тесты

---

### Шаг 3.1: context.py (TDD)

**Что делает:** История шагов, формирование messages для Claude, оценка токенов.

**Интерфейс:**
```python
@dataclass
class Step:
    action: str | None = None
    result: str | None = None
    thinking: str | None = None
    observation: str | None = None

class ContextManager:
    def set_goal(self, goal: str) -> None
    def add_step(self, step: Step) -> None
    def get_step_count(self) -> int
    def estimate_tokens(self) -> int
    def reset(self) -> None
    def set_summary(self, summary: str) -> None
    def build_messages(self) -> list[dict]
```

**Тесты** (`tests/test_context.py`):
- `test_set_goal` — цель попадает в build_messages()
- `test_add_step` — get_step_count() увеличивается
- `test_build_messages_format` — формат Anthropic messages (user/assistant чередование)
- `test_goal_always_first` — messages[0] = user message с целью
- `test_estimate_tokens_positive` — оценка > 0
- `test_reset_clears` — step_count = 0 после reset

**Реализация:**
- `build_messages()`: goal → user message, каждый Step → пара assistant (tool_use) + user (tool_result)
- Если шагов > 10: первые (N-10) сжимаются в текстовую суммаризацию внутри первого user message
- Оценка токенов: `len(text) // 4`

- [x] Тест → код → `pytest tests/test_context.py -v` ✅

---

### Шаг 3.2: prompts.py

**Что делает:** Системный промпт, адаптированный под MCP tools.

```python
SYSTEM_PROMPT = """You are an autonomous AI agent controlling a web browser via MCP tools.

## How You Work
1. Observe page: browser_snapshot → see structure with [ref] markers
2. Think about next action
3. Take ONE action via a tool
4. Observe result, repeat

## Browser Tools (from MCP)
- **Observe:** browser_snapshot (a11y tree with ref markers), browser_take_screenshot
- **Navigate:** browser_navigate(url), browser_go_back, browser_go_forward
- **Interact:** browser_click(ref), browser_hover(ref), browser_type(ref, text),
  browser_select_option(ref, values), browser_press_key(key)
- **Tabs:** browser_tab_list, browser_tab_new(url), browser_tab_select(index),
  browser_tab_close(index)
- **Advanced:** browser_handle_dialog(accept), browser_file_upload(paths),
  browser_wait, browser_resize

## Custom Tools
- **Memory:** remember(key, value), recall(key)
- **User:** ask_user(question), show_preview(title, items), confirm(question)
- **Done:** done(summary)

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


def build_system_prompt(config=None) -> str:
    """Build system prompt, optionally injecting config values."""
    prompt = SYSTEM_PROMPT
    if config:
        prompt += f"\n\n## Current Configuration\n"
        prompt += f"- Max emails to scan: {config.max_emails_to_scan}\n"
        prompt += f"- Max vacancies: {config.max_vacancies}\n"
    return prompt
```

- [x] Создать `agent/prompts.py`

---

### Шаг 3.3: core.py (TDD)

**Что делает:** ReAct-цикл — LLM думает, вызывает tools, получает результат, повторяет.

**Интерфейс:**
```python
class AgentLoop:
    def __init__(self, llm_client, tool_executor, context, config, all_tools: list[dict])
    async def run(self, task: str) -> str
```

**Тесты** (`tests/test_core.py`, все зависимости мокаются):
- `test_returns_summary_on_done` — done() → возвращает summary
- `test_executes_tool_and_continues` — navigate → done (2 шага)
- `test_stops_at_max_steps` — лимит шагов = 3 → сообщение о лимите
- `test_ask_user_gets_input` — ask_user → input() → продолжает
- `test_confirm_yes` — confirm → "да" → result "true"

**Алгоритм `run()`:**
```
1. context.set_goal(task)
2. for step in range(max_steps):
   a. messages = context.build_messages()
   b. response = llm_client.send_message(messages, system_prompt, all_tools)
   c. Если только текст без tools → логируем, continue
   d. Для каждого tool_call:
      - "done" → return summary
      - "ask_user" → input() → result
      - "confirm" → input() → "true"/"false"
      - "show_preview" → print → "preview_shown"
      - остальные → tool_executor.execute() → result
      - context.add_step(...)
      - Запись в audit log (agent_log.jsonl)
3. return "Достигнут лимит шагов"
```

**Audit log:** каждый шаг пишется в `agent_log.jsonl`:
```json
{"step": 1, "tool": "browser_navigate", "args": {"url": "..."}, "result": "...", "timestamp": "..."}
```

- [x] Тест → код → `pytest tests/test_core.py -v` ✅

---

### Шаг 3.4: Финальная проверка блока 3

- [x] `python -m pytest -v` → все тесты зелёные (блоки 1 + 2 + 3)
- [x] CHANGELOG.md

---

## БЛОК 4: Персистентная память

**Цель:** Key-value хранилище, выживающее между сессиями.

**Файлы:** `agent/memory.py`, `tests/test_memory.py`

---

### Шаг 4.1: memory.py (TDD)

**Интерфейс:**
```python
class Memory:
    def __init__(self, filepath: Path = Path("memory.json"), load_env_defaults: bool = False)
    def save(self, key: str, value: str) -> None
    def load(self, key: str) -> str | None
    def has(self, key: str) -> bool
    def delete(self, key: str) -> None
    def list_keys(self) -> list[str]
```

**Тесты** (`tests/test_memory.py`):
- `test_save_and_load` — сохранить и прочитать
- `test_load_missing_returns_none` — несуществующий ключ → None
- `test_has_key` — проверка наличия
- `test_delete_key` — удаление
- `test_list_keys` — список ключей
- `test_data_survives_restart` — новый Memory на том же файле → данные на месте
- `test_loads_env_defaults` — USER_FULL_NAME из env → память
- `test_env_defaults_do_not_overwrite` — существующее значение не перезаписывается

**Реализация:**
- `_data: dict` in-memory кэш + JSON-файл
- `_persist()` → записать, `_load_from_file()` → прочитать
- `load_env_defaults=True`: проверяет `USER_FULL_NAME`, `USER_PHONE`, `USER_EMAIL`, `DELIVERY_ADDRESS` — пишет только если ключа нет

- [ ] Тест → код → `pytest tests/test_memory.py -v` ✅

---

### Шаг 4.2: Финальная проверка блока 4

- [ ] `python -m pytest -v` ✅
- [ ] CHANGELOG.md

---

## БЛОК 5: CLI интерфейс (main.py)

**Цель:** Собрать всё в работающее приложение.

**Файлы:** `main.py`

---

### Шаг 5.1: main.py

**Алгоритм:**
```
1. load_config()
2. Memory(load_env_defaults=True)
3. MCPClient.start(command, args + headless/viewport flags)
4. mcp_tools = MCPClient.list_tools()
5. all_tools = merge_tools(mcp_tools)
6. ToolExecutor(mcp_client, memory).init_mcp_tools()
7. CLI loop:
   - input задачи
   - "quit"/"exit" → выход
   - "memory" → показать память
   - иначе → AgentLoop.run(task)
8. MCPClient.stop()
```

**CLI команды:**
- `<текст>` — задача агенту
- `memory` — содержимое памяти
- `quit` / `exit` / `выход` — завершение

- [ ] Создать `main.py`
- [ ] Проверить: `python main.py` → MCP-сервер стартует, CLI работает
- [ ] Тестовая задача: «Перейди на google.com»

---

### Шаг 5.2: Финальная проверка блока 5

- [ ] `python -m pytest -v` ✅
- [ ] `python main.py` работает
- [ ] CHANGELOG.md

---

## БЛОК 6: Оптимизация и полировка

**Цель:** Prompt caching, сжатие контекста, сохранение сессии, реальные сценарии.

---

### Шаг 6.1: Prompt Caching

В `llm_client.py` — system prompt и tools с `cache_control`:
```python
system = [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]
```
Последний tool в списке тоже с `cache_control`.

- [ ] Добавить caching → тесты проходят

---

### Шаг 6.2: Сжатие контекста

В `context.py` — метод `compress_old_steps(llm_client)`:
- Шагов > 10 → первые (N-10) суммаризируются через LLM
- В `core.py`: если `estimate_tokens() > 30000` → compress

- [ ] Добавить сжатие → тесты проходят

---

### Шаг 6.3: Сохранение сессии браузера

MCP-сервер поддерживает `--save-storage` / `--storage-state` для cookies/session:
```
npx @playwright/mcp --save-storage=./browser_state.json
npx @playwright/mcp --storage-state=./browser_state.json  # повторный запуск
```
Добавить в config: `BROWSER_STORAGE_PATH` → передавать в args MCP-сервера.

- [ ] Добавить сохранение сессии

---

### Шаг 6.4: Тестирование на реальных сценариях

| # | Сценарий | Задача | Ожидание |
|---|---|---|---|
| 1 | iCloud почта | «Прочитай письма и удали спам» | Скан → группировка → превью → подтверждение → удаление |
| 2 | hh.ru | «Найди 5 вакансий AI-инженера и откликнись» | Поиск → сопроводительные → отклик |
| 3 | Доставка еды | «Закажи BBQ-бургер» | Ресторан → блюдо → корзина → адрес → подтверждение |
| 4 | kwork.ru | «Найди заказы и откликнись» | Профиль → заказы → письмо → отклик |

- [ ] Сценарий 1–4 работают

---

### Шаг 6.5: README.md

- [ ] Описание, установка, использование

---

### Шаг 6.6: Финальная проверка

- [ ] Все тесты ✅
- [ ] Все сценарии ✅
- [ ] CHANGELOG.md
- [ ] Демо-видео
