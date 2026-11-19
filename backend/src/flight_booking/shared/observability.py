"""JSON application events. Pass only controlled metadata, never raw inputs."""

import asyncio
import json
import re
from collections.abc import Callable, Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

_context: ContextVar[tuple[str, str] | None] = ContextVar("log_context", default=None)
_correlation_id = re.compile(r"[0-9a-f]{32}")


@contextmanager
def log_context(entry_point: str) -> Iterator[str]:
    run_id = uuid4().hex
    token = _context.set((entry_point, run_id))
    try:
        yield run_id
    finally:
        _context.reset(token)


def log_event(
    module: str,
    event: str,
    *,
    level: str = "INFO",
    correlation_id: object = None,
    **fields: str | float | bool | None,
) -> None:
    entry_point, run_id = _context.get() or ("internal", uuid4().hex)
    # Do not echo arbitrary identifiers supplied in HTTP headers or Redis envelopes.
    if not isinstance(correlation_id, str) or not _correlation_id.fullmatch(correlation_id):
        correlation_id = run_id
    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": level,
                "module": module,
                "event": event,
                "entry_point": entry_point,
                "request_id": run_id,
                "correlation_id": correlation_id,
                **fields,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def run_logged_job(
    module: str,
    operation: str,
    job: Callable[[], Coroutine[Any, Any, int]],
) -> int:
    with log_context("worker"):
        try:
            count = asyncio.run(job())
        except Exception as exc:
            log_event(
                module, "worker_failed", level="ERROR",
                operation=operation, error_type=type(exc).__name__,
            )
            raise
        if count:
            log_event(module, "worker_completed", operation=operation, count=count)
        return count
