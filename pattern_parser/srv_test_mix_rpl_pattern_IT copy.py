from __future__ import annotations

"""
Replay-pattern integration tests.
Each scenario selects a different replay command sequence and validates the
matching replay status events within TIMEOUT_STATUS.
"""

from pathlib import Path
import threading
import time

import pytest

from can_service.chal.base import ChannelState
from can_service.events import ReplayStatusEvent, ReplayStatusType
from file_service.record_id import RecordId
from file_service.srv_if import get_file_service
from can_service.unit_test.can_srv__UT import _parse_log_to_record_id


TIMEOUT_STATUS = 0.5
TIMEOUT_RUN = 10.0

PROJECT_ROOT = Path("/home/gnar911/Desktop/20260516_JOBS_INSPECTOR/project")
REPLAY_SOURCE_FILE = PROJECT_ROOT / "can_service" / "unit_test" / "data_test" / "2025-02-11_11-14-53_仕様情報切替 1_x10.asc"


def _wait_for(event: threading.Event, label: str) -> None:
    assert event.wait(timeout=TIMEOUT_STATUS), f"{label} not received within {TIMEOUT_STATUS}s"


def _confirm_record(file_srv, record_id: RecordId) -> None:
    record = file_srv.get_record(record_id)
    assert record is not None
    record.refresh_runtime()
    runtime_mmap_paths = record.get_runtime_mmap_paths()
    assert runtime_mmap_paths["data"]
    assert runtime_mmap_paths["index"]
    assert all(path.exists() for path in runtime_mmap_paths["data"])
    assert all(path.exists() for path in runtime_mmap_paths["index"])
    assert record.get_total_lines() > 0


@pytest.mark.parametrize(
    "scenario",
    [
        "L1_ST_TIMEOUT",
        "ST_P_R_SP",
        "L_SR2_F100:200_T0.5:1_ST_SP",
    ],
)
def test_IT_PATTERN_REPLAY(can_service, scenario: str) -> None:
    can_srv = can_service
    file_srv = get_file_service()
    snapshot = can_srv.get_channels_snapshot()
    acquired = next((info for info in snapshot.values() if info.state == ChannelState.ACQUIRED), None)
    assert acquired is not None, "no ACQUIRED channel found; reuse existing setup from can_srv__UT.py before running IT"

    replay_started = threading.Event()
    replay_paused = threading.Event()
    replay_resumed = threading.Event()
    replay_stopped = threading.Event()
    replay_looped = threading.Event()
    replay_repeated = threading.Event()
    replay_filter_msg = threading.Event()
    replay_time_scope = threading.Event()

    def _on_replay_status(event: ReplayStatusEvent) -> None:
        if event.status == ReplayStatusType.SOURCE_READY:
            replay_started.set()
        elif event.status == ReplayStatusType.STARTED:
            replay_started.set()
        elif event.status == ReplayStatusType.PAUSED:
            replay_paused.set()
        elif event.status == ReplayStatusType.RESUMED:
            replay_resumed.set()
        elif event.status == ReplayStatusType.STOPPED:
            replay_stopped.set()
        elif event.status == ReplayStatusType.LOOPED:
            replay_looped.set()
        elif event.status == ReplayStatusType.REPEATED:
            replay_repeated.set()
        elif event.status == ReplayStatusType.FILTER_MSG:
            replay_filter_msg.set()
        elif event.status == ReplayStatusType.TIME_SCOPE_SET:
            replay_time_scope.set()

    can_srv.subscribe(ReplayStatusEvent, _on_replay_status)

    record_id = _parse_log_to_record_id(str(REPLAY_SOURCE_FILE))
    _confirm_record(file_srv, record_id)

    if scenario == "L1_ST_TIMEOUT":
        assert can_srv.set_loop(True) is True
        _wait_for(replay_looped, "LOOPED")

        assert can_srv.start_replay(record_id) is True
        _wait_for(replay_started, "SOURCE_READY/STARTED")

        time.sleep(TIMEOUT_RUN)

        assert can_srv.stop_replay() is True
        _wait_for(replay_stopped, "STOPPED")

    elif scenario == "ST_P_R_SP":
        assert can_srv.start_replay(record_id) is True
        _wait_for(replay_started, "SOURCE_READY/STARTED")

        assert can_srv.pause_replay() is True
        _wait_for(replay_paused, "PAUSED")

        assert can_srv.resume_replay() is True
        _wait_for(replay_resumed, "RESUMED")

        assert can_srv.stop_replay() is True
        _wait_for(replay_stopped, "STOPPED")

    elif scenario == "L_SR2_F100:200_T0.5:1_ST_SP":
        assert can_srv.set_loop(True) is True
        _wait_for(replay_looped, "LOOPED")

        assert can_srv.set_repeat(2) is True
        _wait_for(replay_repeated, "REPEATED")

        assert can_srv.set_msg_id_filter([0x100, 0x200]) is True
        _wait_for(replay_filter_msg, "FILTER_MSG")

        start_ts, end_ts = file_srv.get_record(record_id).get_first_last_timestamp()  # type: ignore[union-attr]
        assert start_ts is not None and end_ts is not None
        mid_ts = start_ts + ((end_ts - start_ts) * 0.5)
        assert can_srv.set_time_scope(mid_ts, end_ts) is True
        _wait_for(replay_time_scope, "TIME_SCOPE_SET")

        assert can_srv.start_replay(record_id) is True
        _wait_for(replay_started, "SOURCE_READY/STARTED")

        assert can_srv.stop_replay() is True
        _wait_for(replay_stopped, "STOPPED")

    else:
        pytest.fail(f"unsupported replay scenario: {scenario}")
