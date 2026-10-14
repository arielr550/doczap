"""Converting several documents in one go, as the desktop app does.

Kept free of any GUI code so it can be tested without a display.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from doczap.conversion import convert_document, default_output_path
from doczap.process import ConversionCancelled, check_cancelled


@dataclass
class Job:
    source: Path
    output: Path
    replace: bool = False


@dataclass
class Result:
    converted: list[Job] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False


def plan_jobs(sources: Iterable[Path], output_dir: Path | None = None) -> list[Job]:
    """Pair each document with its PDF: beside the document, or in output_dir."""
    return [
        Job(source, default_output_path(source) if output_dir is None else output_dir / f"{source.stem}.pdf")
        for source in sources
    ]


def run_jobs(
    jobs: Iterable[Job], on_start: Callable[[Job], None] = lambda job: None,
    *, cancel: threading.Event | None = None,
) -> Result:
    """Convert each job in turn, collecting failures instead of stopping at the first."""
    result = Result()
    claimed: set[Path] = set()
    for job in jobs:
        if cancel is not None and cancel.is_set():
            result.cancelled = True
            break
        on_start(job)
        # Two documents with the same name sent to one folder would otherwise
        # silently replace each other's PDF.
        if job.output in claimed:
            result.errors.append(
                f"{job.source.name}: another document in this batch is already saved as "
                f"{job.output.name}."
            )
            continue
        claimed.add(job.output)
        try:
            check_cancelled(cancel)
            convert_document(job.source, job.output, overwrite=job.replace, cancel=cancel)
        except ConversionCancelled:
            result.cancelled = True
            break
        except Exception as exc:
            result.errors.append(f"{job.source.name}: {exc}")
        else:
            result.converted.append(job)
    return result


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def format_summary(result: Result, skipped: int = 0) -> str:
    parts = []
    if len(result.converted) == 1:
        parts.append(f"Created {result.converted[0].output.name}.")
    elif result.converted:
        parts.append(f"Created {plural(len(result.converted), 'PDF')}.")
    if result.cancelled:
        parts.append("Conversion cancelled.")
    if skipped:
        parts.append(f"Skipped {plural(skipped, 'existing PDF')}.")
    if result.errors:
        parts.append(f"{plural(len(result.errors), 'document')} could not be converted.")
    return " ".join(parts) or "Nothing was converted."
