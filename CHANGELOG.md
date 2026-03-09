# CHANGELOG

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
