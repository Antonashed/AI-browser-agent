@echo off
:: =========================================================
:: MyAgent — запуск всего окружения одним кликом
:: 1. Терминал для просмотра логов
:: 2. Терминал с агентом (MCP запустит свой Chromium)
:: =========================================================

set PROJECT_DIR=%~dp0
set LOG_FILE=%PROJECT_DIR%agent.log

:: --- 1. Создаём/очищаем лог-файл ---
type nul > "%LOG_FILE%"

:: --- 2. Терминал для логов ---
echo [1/2] Открываю терминал для логов...
start "MyAgent Logs" cmd /k "title MyAgent Logs & cd /d %PROJECT_DIR% & venv\Scripts\python.exe log_viewer.py"

timeout /t 1 /nobreak >nul

:: --- 3. Терминал с агентом ---
echo [2/2] Запускаю агента (standalone — MCP откроет свой Chromium)...
start "MyAgent" cmd /k "title MyAgent & cd /d %PROJECT_DIR% & venv\Scripts\activate & python main.py"
