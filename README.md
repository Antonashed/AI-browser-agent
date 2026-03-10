# MyAgent — AI Browser Agent

Автономный AI-агент, который получает текстовую задачу и **сам** выполняет её в веб-браузере. Никакого хардкода шагов, селекторов или URL.

## Стек

- **Python 3.13** — основной язык
- **Microsoft Playwright MCP** — управление браузером через MCP-сервер
- **Anthropic Claude Sonnet** — LLM для рассуждений и принятия решений
- **MCP SDK** — протокол взаимодействия с browser-сервером
- **ReAct паттерн** — observe → think → act

## Как это работает

1. Пользователь вводит задачу на естественном языке
2. Агент подключается к Playwright MCP-серверу (браузер)
3. В цикле ReAct: наблюдает страницу (`browser_snapshot`) → думает → выполняет действие
4. Элементы идентифицируются через `ref`-атрибуты из accessibility tree
5. При необходимости спрашивает пользователя, запоминает информацию

## Установка

### Требования

- Python 3.13+
- Node.js (для Playwright MCP-сервера)

### Шаги

```bash
# Клонировать репозиторий
git clone <repo-url>
cd MyAgent

# Создать виртуальное окружение
python -m venv venv
venv\Scripts\activate     # Windows
# source venv/bin/activate  # Linux/macOS

# Установить зависимости
pip install -r requirements.txt

# Установить Playwright MCP-сервер
npm install -g @playwright/mcp

# Создать .env из примера
copy .env.example .env     # Windows
# cp .env.example .env     # Linux/macOS
```

Отредактируйте `.env` — укажите `ANTHROPIC_API_KEY` и при необходимости другие параметры.

## Использование

### Подключение к открытому браузеру (по умолчанию)

Агент по умолчанию подключается к уже запущенному Chrome через CDP — вы видите все действия агента в реальном времени.

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

Для автономного режима (MCP запускает свой браузер) установите в `.env`:

```env
CDP_ENDPOINT=none
```

### Команды CLI

| Команда | Описание |
|---|---|
| `<текст задачи>` | Передать задачу агенту |
| `memory` / `память` | Просмотреть содержимое памяти |
| `выход` / `quit` / `exit` | Завершить работу |

## Конфигурация (.env)

| Переменная | Описание | По умолчанию |
|---|---|---|
| `ANTHROPIC_API_KEY` | API-ключ Anthropic | *(обязательно)* |
| `LLM_MODEL` | Модель LLM | `claude-sonnet-4-20250514` |
| `LLM_MAX_TOKENS` | Макс. токенов ответа | `4096` |
| `MAX_AGENT_STEPS` | Лимит шагов агента | `50` |
| `SCREENSHOT_ENABLED` | Скриншоты | `true` |
| `MCP_BROWSER_COMMAND` | Команда запуска MCP | `npx` |
| `MCP_BROWSER_ARGS` | Аргументы MCP | `@playwright/mcp` |
| `BROWSER_HEADLESS` | Режим без UI | `false` |
| `BROWSER_VIEWPORT_WIDTH` | Ширина окна | `1280` |
| `BROWSER_VIEWPORT_HEIGHT` | Высота окна | `900` |
| `BROWSER_STORAGE_PATH` | Файл сессии браузера | *(пусто)* |
| `CDP_ENDPOINT` | CDP-эндпоинт браузера (`none` = автономный) | `http://localhost:9222` |

## Архитектура

```
main.py                 # CLI точка входа
agent/
├── config.py           # .env → Config dataclass
├── mcp_client.py       # Подключение к Playwright MCP
├── tools.py            # 6 кастомных tools + merge с MCP
├── llm_client.py       # Anthropic API + prompt caching
├── tool_executor.py    # Роутер: MCP / кастомные tools
├── context.py          # История, сжатие контекста
├── memory.py           # Персистентная key-value память
├── prompts.py          # Системный промпт
└── core.py             # AgentLoop — ReAct-цикл
```

## Тесты

```bash
python -m pytest
```

## Лицензия

MIT
