"""Terminal progress with an append-only fallback for pipes and log files."""

import sys
from typing import TextIO

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from .contracts import ProgressEvent


def _literal(value: str) -> str:
    """Make terminal controls visible; skill names must never control the display."""
    return "".join(
        char if char.isprintable() else char.encode("unicode_escape").decode("ascii")
        for char in value
    )


class ProgressReporter:
    """A context-managed observer; all progress goes to stderr by default."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self._progress: Progress | None = None
        self._task = None

    def __enter__(self) -> "ProgressReporter":
        if getattr(self.stream, "isatty", lambda: False)():
            console = Console(
                file=self.stream, force_terminal=True, markup=False, highlight=False,
            )
            self._progress = Progress(
                SpinnerColumn(finished_text="•"),
                TextColumn("{task.description}", markup=False),
                BarColumn(bar_width=20),
                TextColumn("{task.fields[counter]}", markup=False),
                TimeElapsedColumn(),
                console=console,
                transient=True,
                refresh_per_second=8,
                redirect_stdout=False,
                redirect_stderr=False,
            )
            self._task = self._progress.add_task("Preparing", total=None, counter="")
            self._progress.start()
        return self

    def __call__(self, event: ProgressEvent) -> None:
        description = f"{event.operation} · {event.phase}"
        if event.skill is not None:
            description += f" · {_literal(event.skill)}"
        counter = "" if event.total is None else f"{event.completed}/{event.total} processed"
        if self._progress is not None and self._task is not None:
            self._progress.update(
                self._task, description=description, total=event.total,
                completed=event.completed, counter=counter, refresh=True,
            )
        else:
            line = f"{description} · {counter}" if counter else description
            print(line, file=self.stream, flush=True)

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            if self._progress is not None:
                self._progress.stop()
        finally:
            self._progress = None
            self._task = None
        return False
