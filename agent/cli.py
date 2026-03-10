"""Rich-based CLI for the AI Browser Agent."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from agent.events import AgentEvent, EventType

_THEME = Theme({
    "info": "cyan",
    "success": "green",
    "warning": "yellow",
    "error": "bold red",
    "dim": "dim italic",
    "tool": "bold magenta",
    "cost": "dim cyan",
})


class CLI:
    """Handles all terminal output through Rich."""

    def __init__(self) -> None:
        self.console = Console(theme=_THEME)
        self._thinking_lines: list[str] = []
        self._thinking_active = False

    def print_banner(self, tool_count: int, mcp_count: int, mode: str) -> None:
        banner = Text()
        banner.append("AI Browser Agent", style="bold cyan")
        banner.append("\n")
        banner.append(f"Tools: {tool_count} ", style="info")
        banner.append(f"(MCP: {mcp_count}, custom: {tool_count - mcp_count})", style="dim")
        banner.append(f"\nMode: {mode}", style="dim")
        self.console.print(Panel(banner, border_style="cyan", padding=(0, 1)))

    def print_help(self) -> None:
        table = Table(title="Команды", border_style="cyan", show_header=True)
        table.add_column("Команда", style="bold")
        table.add_column("Описание")
        table.add_row("/help, /h", "Показать справку")
        table.add_row("/memory, /m", "Просмотр памяти агента")
        table.add_row("/plan <задача>", "Составить план (без выполнения)")
        table.add_row("/go", "Выполнить последний план")
        table.add_row("/history", "Список задач за сессию")
        table.add_row("/cost", "Расход токенов за сессию")
        table.add_row("/exit, /quit", "Завершить работу")
        self.console.print(table)

    def print_memory(self, memory_data: dict[str, str]) -> None:
        if not memory_data:
            self.console.print("  (память пуста)", style="dim")
            return
        for key, value in memory_data.items():
            self.console.print(f"  [bold]{key}[/bold]: {value}")

    def print_plan(self, plan_text: str) -> None:
        self.console.print(Panel(plan_text, title="План", border_style="cyan", padding=(0, 1)))
        self.console.print("  Введите [bold]/go[/bold] для выполнения или новую задачу.\n", style="dim")

    def print_result(self, summary: str) -> None:
        self.console.print(f"\n  [success]✓[/success] {summary}")

    def print_usage(self, steps: int, input_tokens: int, output_tokens: int) -> None:
        cost_input = input_tokens * 3 / 1_000_000
        cost_output = output_tokens * 15 / 1_000_000
        cost_total = cost_input + cost_output
        self.console.print(
            f"  [cost]── {steps} шагов · {input_tokens // 1000}K in · "
            f"{output_tokens // 1000}K out · ${cost_total:.2f} ──[/cost]\n"
        )

    def print_session_cost(self, total_input: int, total_output: int, task_count: int) -> None:
        cost_input = total_input * 3 / 1_000_000
        cost_output = total_output * 15 / 1_000_000
        cost_total = cost_input + cost_output
        table = Table(title="Расход за сессию", border_style="cyan")
        table.add_column("Метрика", style="bold")
        table.add_column("Значение", justify="right")
        table.add_row("Задач выполнено", str(task_count))
        table.add_row("Input токены", f"{total_input:,}")
        table.add_row("Output токены", f"{total_output:,}")
        table.add_row("Стоимость", f"${cost_total:.3f}")
        self.console.print(table)

    def print_history(self, tasks: list[str]) -> None:
        if not tasks:
            self.console.print("  (нет выполненных задач)", style="dim")
            return
        for i, task in enumerate(tasks, 1):
            self.console.print(f"  {i}. {task}")

    def print_error(self, message: str) -> None:
        self.console.print(f"  [error]✗ {message}[/error]")

    def print_status(self, message: str) -> None:
        self.console.print(f"  [dim]{message}[/dim]")

    def print_connecting(self, headless: bool = False) -> None:
        self.console.print(f"  [info]Режим:[/info] standalone (headless={headless})")

    # --- Event handling for streaming ---

    def handle_event(self, event: AgentEvent) -> None:
        """Route an AgentEvent to the appropriate display method."""
        match event.type:
            case EventType.THINKING_DELTA:
                self._handle_thinking_delta(event.data.get("text", ""))
            case EventType.TEXT_DELTA:
                pass  # text deltas are part of text-only responses, not displayed during tool loop
            case EventType.TOOL_START:
                self._finish_thinking()
                name = event.data.get("name", "?")
                args_str = _format_args(event.data.get("args", {}))
                self.console.print(f"  [tool]→[/tool] {name} {args_str}", end="")
            case EventType.TOOL_RESULT:
                elapsed = event.data.get("elapsed", 0)
                is_error = event.data.get("is_error", False)
                if is_error:
                    self.console.print(f"  [error]✗ {elapsed}s[/error]")
                else:
                    self.console.print(f"  [success]✓ {elapsed}s[/success]")
            case EventType.ASK_USER:
                self._finish_thinking()
                question = event.data.get("question", "")
                self.console.print(f"\n  [info]?[/info] {question}")
            case EventType.CONFIRM:
                self._finish_thinking()
                question = event.data.get("question", "")
                self.console.print(f"\n  [warning]?[/warning] {question}")
            case EventType.SHOW_PREVIEW:
                self._finish_thinking()
                title = event.data.get("title", "")
                items = event.data.get("items", [])
                self.console.print(f"\n  [info]📋 {title}[/info]")
                for i, item in enumerate(items, 1):
                    self.console.print(f"    {i}. {item}")
            case EventType.DONE:
                self._finish_thinking()
            case EventType.ERROR:
                self._finish_thinking()
                self.print_error(event.data.get("message", "Unknown error"))
            case EventType.STATUS:
                self.print_status(event.data.get("message", ""))

    def _handle_thinking_delta(self, text: str) -> None:
        if not self._thinking_active:
            self._thinking_active = True
            self.console.print()  # newline before thinking block
            self._thinking_lines = []

        self._thinking_lines.append(text)
        # Print last chunk inline (streaming effect)
        self.console.print(f"  [dim]{text}[/dim]", end="")

    def _finish_thinking(self) -> None:
        if self._thinking_active:
            self.console.print()  # finish the thinking line
            self._thinking_active = False
            self._thinking_lines.clear()

    def prompt_task(self) -> str:
        """Show the input prompt and return the user's input."""
        self.console.print()
        return self.console.input("[bold]> [/bold]").strip()


def _format_args(args: dict) -> str:
    """Format tool args for display — short, readable."""
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        s = str(v)
        if len(s) > 60:
            s = s[:57] + "..."
        parts.append(f'{k}="{s}"' if isinstance(v, str) else f"{k}={s}")
    result = " ".join(parts)
    return f"[dim]{result}[/dim]" if result else ""
