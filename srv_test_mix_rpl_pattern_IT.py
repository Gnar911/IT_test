from __future__ import annotations

"""
Replay-pattern integration tests.
At this level of test case we not use QApplicaiton and processEvent for test anymore,
instead we use pip install pytest-qt and qbot wait.
"""
from pathlib import Path
import threading
import time

import pytest

from can_service.chal.base import ChannelState
from can_service.events import ReplayStatusType
from can_service.replay.rpl_cmd import ReplayCmdType
from file_service.api.srv_if import get_file_service
from file_service.module.fs_core import ParsedEntry
from fixture import AllService

TIMEOUT_STATUS = 0.5 # Time for the reponse status from worker since got the command
TIMEOUT_RUN = 10.0 # Default time out for infinite run case

PROJECT_ROOT = Path("/home/gnar911/Desktop/20260516_JOBS_INSPECTOR/project")
DEFAULT_REPLAY_SOURCE_FILE = PROJECT_ROOT / "can_service" / "unit_test" / "data_test" / "2025-02-11_11-14-53_仕様情報切替 1_x10.asc"
REPLAY_SOURCE_FILES = [str(DEFAULT_REPLAY_SOURCE_FILE)]

"""
Pattern syntax:
    ST          = START
    P           = PAUSE
    SP          = STOP
    R           = RESUME
    L / L1      = SET_LOOP (enable)
    L0          = SET_LOOP (disable)
    SR<n>       = SET_REPEAT(<n>), e.g., SR2, SR5
    F<ids>      = SET_FILTER_MSG, e.g., F100:200:300
    T<s>:<e>    = SET_TIME_SCOPE (0..1 normalized span, >1 as start-offset seconds), e.g., T0.5:1
    <number>    = sleep duration in seconds
    W<status>   = wait for status, e.g., WFINISH, WFINISHED, WPAUSED
    X           = EXIT
"""

REPLAY_SCENARIOS = [
    (
        "L1_ST_TIMEOUT", # Pattern
        [
               (ReplayCmdType.SET_LOOP, True),
               (ReplayCmdType.START, None),
               ("SLEEP", TIMEOUT_RUN),
               (ReplayCmdType.STOP, None),
        ],
        ["Loop, start, then stop after TIMEOUT_RUN"], # Description
    ),
    (
        "ST_P_R_SP", # Pattern
        [
               (ReplayCmdType.START, None),
               (ReplayCmdType.PAUSE, None),
               (ReplayCmdType.RESUME, None),
               (ReplayCmdType.STOP, None),
        ],
        ["Start, pause, resume, stop"], # Description
    ),
    (
        "L_SR2_F100:200_T0.5:1_ST_SP",
        [
               (ReplayCmdType.SET_LOOP, True),
               (ReplayCmdType.SET_REPEAT, 2),
               (ReplayCmdType.SET_FILTER_MSG, [0x100, 0x200]),
            (
                   ReplayCmdType.SET_TIME_SCOPE,
                lambda metadata: (
                    metadata["time_range"][0] + ((metadata["time_range"][1] - metadata["time_range"][0]) * 0.5),
                    metadata["time_range"][1],
                ),
            ),
               (ReplayCmdType.START, None),
               (ReplayCmdType.STOP, None),
        ],
        ["Loop, repeat twice, filter 0x100/0x200, set time scope, start, stop"], # Description
    ),
]


@pytest.mark.parametrize("replay_source_file", REPLAY_SOURCE_FILES)
@pytest.mark.parametrize("pattern, replay_commands, _description", REPLAY_SCENARIOS)
def test_IT_PATTERN_REPLAY(
	all_service: AllService,
	acquired_channels,
	qtbot,
	pattern: str,
	replay_source_file: str,
	replay_commands: list[tuple],
	_description: list[str],
) -> None:
	can_srv, vm = all_service
	file_srv = get_file_service()
	vm.reset_replay()
	vm.reset_parser()
	vm.reset_recorder()
	progress_stop = threading.Event()
	progress_samples: list[int] = []
	progress_thread: threading.Thread | None = None
	recorder_record_id = None
	snapshot = can_srv.get_channels_snapshot()
	acquired = next((info for info in snapshot.values() if info.state == ChannelState.ACQUIRED), None)
	assert acquired is not None, "no ACQUIRED channel found; reuse existing setup from can_srv__UT.py before running IT"
	assert file_srv.start_recording() is True
	qtbot.waitUntil(lambda: vm.recorder_active_event.is_set(), timeout=int(TIMEOUT_STATUS * 1000))
	recorder_record_id = vm.recorder_record_id
	assert recorder_record_id is not None
	recorder_record = file_srv.get_record(recorder_record_id)
	assert recorder_record is not None

	def _track_progress() -> None:
		while not progress_stop.is_set():
			progress = int(recorder_record.get_progress_index())
			progress_samples.append(progress)
			time.sleep(0.05)

	progress_thread = threading.Thread(target=_track_progress, daemon=True, name="mix-rpl-progress")
	progress_thread.start()

	assert file_srv.parse_log(replay_source_file) is True
	assert vm.parser_done_event.wait(timeout=TIMEOUT_RUN), f"parse did not complete within timeout for: {replay_source_file}"
	record_id = vm.parser_record_id
	assert record_id is not None
	record = file_srv.get_record(record_id)
	assert record is not None
	source_metadata = record.get_metadata()
	assert source_metadata["row_size"] > 0
	assert source_metadata["can_ids"]
	assert source_metadata["channels"]
	assert source_metadata["time_range"][0] is not None
	assert source_metadata["time_range"][1] is not None
	assert source_metadata["time_range"][0] <= source_metadata["time_range"][1]

	for idx, command_item in enumerate(replay_commands):
		command = command_item[0] if isinstance(command_item, tuple) else command_item
		command_payload = command_item[1] if isinstance(command_item, tuple) and len(command_item) > 1 else None
		if isinstance(command_payload, tuple) and len(command_payload) == 2 and callable(command_payload[0]):
			command_payload = command_payload[0](source_metadata)

		if command is ReplayCmdType.SET_LOOP:
			can_srv.set_loop(bool(command_payload))
			qtbot.waitUntil(
				lambda: ReplayStatusType.LOOPED in vm.status_trace,
				timeout=int(TIMEOUT_STATUS * 1000),
			)
		elif command is ReplayCmdType.START:
			assert can_srv.start_replay(record_id) is True
			assert vm.started_event.wait(timeout=TIMEOUT_STATUS)
		elif command is ReplayCmdType.PAUSE:
			assert can_srv.pause_replay() is True
			assert vm.paused_event.wait(timeout=TIMEOUT_STATUS)
		elif command is ReplayCmdType.RESUME:
			assert can_srv.resume_replay() is True
			assert vm.resumed_event.wait(timeout=TIMEOUT_STATUS)
		elif command is ReplayCmdType.STOP:
			assert can_srv.stop_replay() is True
			assert vm.stopped_event.wait(timeout=TIMEOUT_STATUS)
		elif command is ReplayCmdType.SET_REPEAT:
			can_srv.set_repeat(int(command_payload))
			qtbot.waitUntil(
				lambda: ReplayStatusType.REPEATED in vm.status_trace,
				timeout=int(TIMEOUT_STATUS * 1000),
			)
		elif command is ReplayCmdType.SET_FILTER_MSG:
			can_srv.set_msg_id_filter(list(command_payload))
			qtbot.waitUntil(
				lambda: ReplayStatusType.FILTER_MSG in vm.status_trace,
				timeout=int(TIMEOUT_STATUS * 1000),
			)
		elif command is ReplayCmdType.SET_TIME_SCOPE:
			can_srv.set_time_scope(command_payload[0], command_payload[1])
			qtbot.waitUntil(
				lambda: ReplayStatusType.TIME_SCOPE_SET in vm.status_trace,
				timeout=int(TIMEOUT_STATUS * 1000),
			)
		elif command == "SLEEP":
			time.sleep(float(command_payload))
		else:
			pytest.fail(f"unsupported replay command in scenario: {command}")

		if idx < len(replay_commands) - 1 and command != "SLEEP":
			time.sleep(0.1)

	assert file_srv.stop_recording() is True
	qtbot.waitUntil(lambda: vm.recorder_stopped_event.is_set(), timeout=int(TIMEOUT_STATUS * 1000))
	progress_stop.set()
	progress_thread.join(timeout=2.0)

	record_after_stop = file_srv.get_record(record_id)
	assert record_after_stop is not None
	metadata = record_after_stop.get_metadata()
	assert metadata["row_size"] > 0
	assert metadata["can_ids"]
	assert metadata["channels"]
	assert metadata["time_range"][0] is not None
	assert metadata["time_range"][1] is not None
	assert metadata["time_range"][0] <= metadata["time_range"][1]
