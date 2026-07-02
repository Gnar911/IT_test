"""Interpret compact replay test-pattern values into concrete replay payloads.

This module converts abstract pattern tokens (ordinal filters and normalized
or relative time scope values) into concrete values consumed by ReplayCmdType
commands in message_replayer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from can_sdk.data_object import CANLogRawDiskFile


def resolve_filter_msg_ids(
    ordinal_indices: list[int],
    source_rows: list[Any],
) -> tuple[list[int], list[str]]:
    """Map ordinal filter ids (F1, F2, ...) to concrete CAN IDs.

    Returns a tuple of:
    - actual_msg_ids: resolved CAN IDs to pass to SET_FILTER_MSG
    - warnings: range warnings for invalid ordinals
    """
    unique_can_ids = sorted(set(int(row.can_id) for row in source_rows))
    actual_msg_ids: list[int] = []
    warnings: list[str] = []

    for ordinal in ordinal_indices:
        if 1 <= int(ordinal) <= len(unique_can_ids):
            actual_msg_ids.append(int(unique_can_ids[int(ordinal) - 1]))
        else:
            warnings.append(
                f"warn: ordinal F{ordinal} out of range (unique IDs: {len(unique_can_ids)})"
            )

    return actual_msg_ids, warnings


def resolve_time_scope(
    start_raw: float | None,
    end_raw: float | None,
    source_ts_start: float,
    source_ts_end: float,
) -> tuple[float | None, float | None]:
    """Resolve T<s>:<e> into concrete timestamps for SET_TIME_SCOPE.

    Semantics:
    - 0 <= value <= 1: normalized ratio across source timestamp span.
      Example: T0.5:1 => middle to end.
    - value > 1: treated as offset seconds from source_ts_start.
      This keeps compatibility for existing patterns that used offsets.
    """
    source_start = float(source_ts_start)
    source_end = float(source_ts_end)
    source_span = max(0.0, source_end - source_start)

    def _resolve(value: float | None) -> float | None:
        if value is None:
            return None
        v = float(value)
        if 0.0 <= v <= 1.0:
            return source_start + (source_span * v)
        return source_start + v

    start_ts = _resolve(start_raw)
    end_ts = _resolve(end_raw)

    if start_ts is not None and end_ts is not None and start_ts > end_ts:
        start_ts, end_ts = end_ts, start_ts

    return start_ts, end_ts


def resolve_time_scope_window(
    start_ts: float | None,
    end_ts: float | None,
    data_base_path: str | Path,
    index_base_path: str | Path,
    source_rows: list[Any],
    ignored_msg_ids: list[int] | None = None,
) -> dict[str, float | int | None]:
    """Resolve exact row bounds and target rows for the current scope/filter state."""
    total_rows = max(0, int(len(source_rows)))
    if total_rows <= 0:
        return {
            "start_ts": start_ts,
            "end_ts": end_ts,
            "scope_start_row": 0,
            "scope_end_row": 0,
            "target_rows": 0,
        }

    log_file = CANLogRawDiskFile(
        file_path=str(Path(data_base_path).with_suffix(".asc")),
        data_mmap_path=str(data_base_path),
        index_mmap_path=str(index_base_path),
    )
    log_file.refresh_mmap_runtime()

    scope_start_row = 0
    scope_end_row = total_rows
    if start_ts is not None:
        scope_start_row = int(log_file.get_start_row_by_timestamp(float(start_ts)))
    if end_ts is not None:
        scope_end_row = int(log_file.get_end_row_by_timestamp(float(end_ts)))

    scope_start_row = max(0, min(scope_start_row, total_rows))
    scope_end_row = max(scope_start_row, min(scope_end_row, total_rows))

    ignored_ids = {int(value) for value in (ignored_msg_ids or [])}
    if ignored_ids:
        target_rows = sum(
            1
            for row in source_rows[scope_start_row:scope_end_row]
            if int(row.can_id) not in ignored_ids
        )
    else:
        target_rows = max(0, int(scope_end_row - scope_start_row))

    return {
        "start_ts": start_ts,
        "end_ts": end_ts,
        "scope_start_row": int(scope_start_row),
        "scope_end_row": int(scope_end_row),
        "target_rows": int(target_rows),
    }


def resolve_time_scope_payload(
    start_raw: float | None,
    end_raw: float | None,
    source_ts_start: float,
    source_ts_end: float,
    data_base_path: str | Path,
    index_base_path: str | Path,
    source_rows: list[Any],
    ignored_msg_ids: list[int] | None = None,
) -> dict[str, float | int | None]:
    """Resolve T<s>:<e> into concrete timestamps and exact row bounds."""
    start_ts, end_ts = resolve_time_scope(
        start_raw=start_raw,
        end_raw=end_raw,
        source_ts_start=source_ts_start,
        source_ts_end=source_ts_end,
    )
    payload = resolve_time_scope_window(
        start_ts=start_ts,
        end_ts=end_ts,
        data_base_path=data_base_path,
        index_base_path=index_base_path,
        source_rows=source_rows,
        ignored_msg_ids=ignored_msg_ids,
    )
    payload["raw_start"] = start_raw
    payload["raw_end"] = end_raw
    return payload