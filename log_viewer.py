"""Live log viewer for MyAgent — colored, filtered, real-time."""

from __future__ import annotations

import argparse
import os
import sys
import time


# ANSI color codes
COLORS = {
    "DEBUG": "\033[90m",     # gray
    "INFO": "\033[36m",      # cyan
    "WARNING": "\033[33m",   # yellow
    "ERROR": "\033[31m",     # red
    "CRITICAL": "\033[91m",  # bright red
}
RESET = "\033[0m"
BOLD = "\033[1m"


def colorize(line: str) -> str:
    for level, color in COLORS.items():
        if f"[{level}]" in line:
            return f"{color}{line}{RESET}"
    return line


def tail_follow(path: str, level_filter: str | None, module_filter: str | None) -> None:
    """Tail a log file, following new writes like `tail -f`."""
    # Wait for file to exist
    while not os.path.exists(path):
        print(f"\033[90mОжидаю создания {path}...\033[0m")
        time.sleep(1)

    with open(path, encoding="utf-8", errors="replace") as f:
        # Jump to end
        f.seek(0, 2)
        print(f"{BOLD}📋 MyAgent Log Viewer{RESET}")
        print(f"{BOLD}   Файл: {path}{RESET}")
        if level_filter:
            print(f"{BOLD}   Фильтр уровня: {level_filter}+{RESET}")
        if module_filter:
            print(f"{BOLD}   Фильтр модуля: {module_filter}{RESET}")
        print(f"{BOLD}{'─' * 60}{RESET}\n")

        level_priority = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
        min_priority = level_priority.get(level_filter or "DEBUG", 0)

        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)
                continue

            line = line.rstrip("\n\r")
            if not line:
                continue

            # Level filter
            if level_filter:
                matched = False
                for lvl, pri in level_priority.items():
                    if f"[{lvl}]" in line and pri >= min_priority:
                        matched = True
                        break
                if not matched:
                    # If line has no level tag, show it (continuation line)
                    has_any_level = any(f"[{l}]" in line for l in level_priority)
                    if has_any_level:
                        continue

            # Module filter
            if module_filter and module_filter.lower() not in line.lower():
                continue

            print(colorize(line))


def main() -> None:
    parser = argparse.ArgumentParser(description="MyAgent — просмотр логов в реальном времени")
    parser.add_argument("file", nargs="?", default="agent.log", help="Путь к лог-файлу (по умолчанию: agent.log)")
    parser.add_argument("-l", "--level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default=None,
                        help="Минимальный уровень логирования")
    parser.add_argument("-m", "--module", default=None,
                        help="Фильтр по имени модуля (например: llm_client, core, mcp)")
    args = parser.parse_args()

    try:
        tail_follow(args.file, args.level, args.module)
    except KeyboardInterrupt:
        print(f"\n{RESET}Завершено.")
        sys.exit(0)


if __name__ == "__main__":
    main()
