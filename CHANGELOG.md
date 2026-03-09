# CHANGELOG

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
