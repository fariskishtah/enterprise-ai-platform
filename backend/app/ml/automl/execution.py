"""Spawn-safe killable process boundary for one bounded CV request."""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from time import monotonic

from app.ml.automl.cross_validation import (
    CrossValidationRequest,
    CrossValidationResult,
    execute_cross_validation,
)


@dataclass(frozen=True, slots=True)
class ProcessExecutionOutcome:
    result: CrossValidationResult | None
    error_code: str | None
    safe_error_message: str | None

    @property
    def succeeded(self) -> bool:
        return self.result is not None


def execute_with_timeout(
    request: CrossValidationRequest,
    *,
    timeout_seconds: float,
    cancelled: Callable[[], bool] | None = None,
) -> ProcessExecutionOutcome:
    """Terminate and join a spawned child on timeout or cancellation."""
    if timeout_seconds <= 0:
        raise ValueError("The process timeout must be positive.")
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_child_entry,
        args=(request.model_dump(mode="json"), child),
        daemon=False,
    )
    try:
        process.start()
    except (OSError, RuntimeError):
        parent.close()
        child.close()
        return ProcessExecutionOutcome(
            None,
            "process_start_failed",
            "The isolated trial process could not be started.",
        )
    child.close()
    deadline = monotonic() + timeout_seconds
    try:
        while process.is_alive():
            if cancelled is not None and cancelled():
                _terminate(process)
                return ProcessExecutionOutcome(
                    None, "cancelled", "The AutoML trial was cancelled."
                )
            remaining = deadline - monotonic()
            if remaining <= 0:
                _terminate(process)
                return ProcessExecutionOutcome(
                    None,
                    "trial_timeout",
                    "The AutoML trial exceeded its execution timeout.",
                )
            process.join(min(remaining, 0.05))
        process.join()
        if parent.poll():
            payload = parent.recv()
            if not isinstance(payload, dict):
                raise ValueError("Invalid child response.")
            if payload.get("ok") is True and isinstance(payload.get("result"), dict):
                return ProcessExecutionOutcome(
                    CrossValidationResult.model_validate(payload["result"]), None, None
                )
            return ProcessExecutionOutcome(
                None,
                str(payload.get("error_code", "trial_execution_failed")),
                "The AutoML trial could not be evaluated.",
            )
        return ProcessExecutionOutcome(
            None,
            "child_process_failed",
            "The isolated AutoML trial process exited unexpectedly.",
        )
    except (EOFError, OSError, ValueError):
        return ProcessExecutionOutcome(
            None,
            "child_process_failed",
            "The isolated AutoML trial process returned an invalid result.",
        )
    finally:
        if process.is_alive():
            _terminate(process)
        else:
            process.join()
        parent.close()


def _child_entry(payload: dict[str, object], connection: Connection) -> None:
    try:
        request = CrossValidationRequest.model_validate(payload)
        result = execute_cross_validation(request)
        connection.send({"ok": True, "result": result.model_dump(mode="json")})
    except (ValueError, TypeError):
        connection.send({"ok": False, "error_code": "trial_validation_failed"})
    except Exception:
        connection.send({"ok": False, "error_code": "trial_execution_failed"})
    finally:
        connection.close()


def _terminate(process: BaseProcess) -> None:
    process.terminate()
    process.join(timeout=2)
    if process.is_alive():
        process.kill()
        process.join()
