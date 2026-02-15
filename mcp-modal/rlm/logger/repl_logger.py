from rich.console import Console
from rich.syntax import Syntax
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.rule import Rule
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class CodeExecution:
    code: str
    stdout: str
    stderr: str
    execution_number: int
    execution_time: Optional[float] = None

class REPLEnvLogger:
    def __init__(self, max_output_length: int = 2000, enabled: bool = True):
        self.enabled = enabled
        self.console = Console()
        self.executions: List[CodeExecution] = []
        self.execution_count = 0
        self.max_output_length = max_output_length
    
    def _truncate_output(self, text: str) -> str:
        """Truncate text output to prevent overwhelming console output."""
        if len(text) <= self.max_output_length:
            return text
        
        # Show first half, then ellipsis, then last half
        half_length = self.max_output_length // 2
        first_part = text[:half_length]
        last_part = text[-half_length:]
        truncated_chars = len(text) - self.max_output_length
        
        return f"{first_part}\n\n... [TRUNCATED {truncated_chars} characters] ...\n\n{last_part}"
    
    def log_execution(self, code: str, stdout: str, stderr: str = "", execution_time: Optional[float] = None) -> None:
        """Log a code execution with its output"""
        self.execution_count += 1
        execution = CodeExecution(
            code=code,
            stdout=stdout,
            stderr=stderr,
            execution_number=self.execution_count,
            execution_time=execution_time
        )
        self.executions.append(execution)
    
    def display_last(self) -> None:
        """Display the last logged execution"""
        if not self.enabled:
            return
        if self.executions:
            self._display_single_execution(self.executions[-1])
    
    def display_all(self) -> None:
        """Display all logged executions in Jupyter-like format"""
        if not self.enabled:
            return
        for i, execution in enumerate(self.executions):
            self._display_single_execution(execution)
            # Add divider between cells (but not after the last one)
            if i < len(self.executions) - 1:
                self.console.print(Rule(style="dim", characters="─"))
                self.console.print()
    
    def _display_single_execution(self, execution: CodeExecution) -> None:
        """Display a single code execution like a Jupyter cell"""
        if not self.enabled:
            return
        # Input cell (code) - also truncate if too long
        timing_panel = None
        display_code = self._truncate_output(execution.code)
        input_panel = Panel(
            Syntax(display_code, "python", theme="monokai", line_numbers=True),
            title=f"[bold blue]In [{execution.execution_number}]:[/bold blue]",
            border_style="blue",
            box=box.ROUNDED
        )
        self.console.print(input_panel)
        
        # Output cell
        if execution.stderr:
            # Error output
            display_stderr = self._truncate_output(execution.stderr)
            error_text = Text(display_stderr, style="bold red")
            output_panel = Panel(
                error_text,
                title=f"[bold red]Error in [{execution.execution_number}]:[/bold red]",
                border_style="red",
                box=box.ROUNDED
            )
        elif execution.stdout:
            # Normal output with separate timing panel if available
            display_stdout = self._truncate_output(execution.stdout)
            output_text = Text(display_stdout, style="white")
            
            output_panel = Panel(
                output_text,
                title=f"[bold green]Out [{execution.execution_number}]:[/bold green]",
                border_style="green",
                box=box.ROUNDED
            )
            # Show timing as a separate panel for reliable rendering
            if execution.execution_time is not None:
                timing_panel = Panel(
                    Text(f"Execution time: {execution.execution_time:.4f}s", style="bright_black"),
                    border_style="grey37",
                    box=box.ROUNDED,
                    title=f"[bold grey37]Timing [{execution.execution_number}]:[/bold grey37]"
                )
        else:
            # No output but still show timing if available
            if execution.execution_time is not None:
                timing_text = Text(f"Execution time: {execution.execution_time:.4f}s", style="dim")
                output_panel = Panel(
                    timing_text,
                    title=f"[bold dim]Out [{execution.execution_number}]:[/bold dim]",
                    border_style="dim",
                    box=box.ROUNDED
                )
                timing_panel = Panel(
                    Text(f"Execution time: {execution.execution_time:.4f}s", style="bright_black"),
                    border_style="grey37",
                    box=box.ROUNDED,
                    title=f"[bold grey37]Timing [{execution.execution_number}]:[/bold grey37]"
                )
            else:
                output_panel = Panel(
                    Text("No output", style="dim"),
                    title=f"[bold dim]Out [{execution.execution_number}]:[/bold dim]",
                    border_style="dim",
                    box=box.ROUNDED
                )
        
        self.console.print(output_panel)
        if timing_panel:
            self.console.print(timing_panel)
    
    def clear(self) -> None:
        """Clear all logged executions"""
        self.executions.clear()
        self.execution_count = 0