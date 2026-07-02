from __future__ import annotations

"""
At this level of test case we not use QApplicaiton and processEvent for test anymore, instead we use pip install pytest-qt and qbot wait.
"""
from pathlib import Path
import threading
import time
import pytest
from file_service.module.fs_core import ParsedEntry
from file_service.srv_if import get_file_service
from fixture import CANService, FileService, TestServices, all_service
# pytest_plugins = ("srv_fixture",)

TIMEOUT_STATUS = 0.5
QT_TIMEOUT_STATUS = TIMEOUT_STATUS *1000
RUN_TIMEOUT = 20.0
QT_TIMEOUT_RUN = RUN_TIMEOUT * 1000
	
def test_01_start_recording_send_upload_metrics(all_service: tuple[CANService, FileService, TestServices], qtbot) -> None:
	can_srv, file_srv, vm = all_service
	
	can_id_1 = 0x5A1
	can_id_2 = 0x5A2

	entry_1 = file_srv.parse_line("0.000001 1 5A1 Tx d 8 01 02 03 04 05 06 07 08")
	entry_2 = file_srv.parse_line("0.000001 1 5A2 Tx d 8 11 12 13 14 15 16 17 18")

	vm.start_track_progress_thread()	
	assert file_srv.start_recording() is True
	vm.recorder_active_event.wait(RUN_TIMEOUT)
	assert vm.record is not None
	
	""" Take the device to send loop"""
	acquired_device_info = vm.acquired_devices[0]
	assert can_srv.send_msg_loop(acquired_device_info, entry_1, initial_periodic=0.04) is True
	vm.snd_add_event.wait(TIMEOUT_STATUS)	
	assert can_srv.send_msg_loop(acquired_device_info, entry_2, initial_periodic=0.04) is True
	#qtbot.waitUntil(lambda: vm.snd_add_event.is_set(), timeout=QT_TIMEOUT_STATUS)
	vm.snd_add_event.wait(TIMEOUT_STATUS)

	qtbot.wait(5000)
	assert can_srv.remove_msg(acquired_device_info, entry_1) is True
	assert vm.snd_remove_event.wait(TIMEOUT_STATUS)
	assert can_srv.remove_msg(acquired_device_info, entry_2) is True
	assert vm.snd_remove_event.wait(TIMEOUT_STATUS)

	vm.fetch_page()
	expected_payloads = {
		can_id_1: "01 02 03 04 05 06 07 08",
		can_id_2: "11 12 13 14 15 16 17 18",
	}
	seen_can_ids: set[int] = set()
	for entry in vm.entries:
		entry_can_id = int(entry.can_id)
		entry_data_len = int(entry.data_len)
		entry_hex = " ".join(f"{int(entry.data[i]):02X}" for i in range(entry_data_len))
		assert entry_can_id in expected_payloads
		assert entry_data_len == 8
		assert entry_hex == expected_payloads[entry_can_id]
		seen_can_ids.add(entry_can_id)
	assert seen_can_ids == {can_id_1, can_id_2}

@pytest.mark.parametrize(
	"replay_source_file",
	[
        Path(__file__).parent / "data_test" / "2025-02-11_11-14-53_仕様情報切替 1.asc",
        Path(__file__).parent / "data_test" / "2025-02-11_11-14-53_仕様情報切替 1_x10.asc",
	],
)
def test_02_start_recording_replay_upload_metrics(all_service: tuple[CANService, FileService, TestServices], qtbot, replay_source_file: str) -> None:
	can_srv, file_srv, vm = all_service
	vm.start_track_progress_thread()
	assert file_srv.start_recording() is True
	vm.recorder_active_event.wait(TIMEOUT_STATUS)
	
	assert vm.record_id is not None

	assert file_srv.parse_log(replay_source_file) is True
	vm.parser_done_event.wait(TIMEOUT_STATUS)

	assert vm.parser_record_id is not None

	assert can_srv.start_replay(vm.parser_record_id) is True
	assert vm.replay_started_event.wait(timeout=TIMEOUT_STATUS), "STARTED not received"

	qtbot.wait(5000)

	assert can_srv.stop_replay() is True
	qtbot.waitUntil(lambda: vm.replay_stopped_event.is_set(), timeout=QT_TIMEOUT_STATUS)

	file_srv.stop_recording()
	qtbot.waitUntil(lambda: vm.recorder_stopped_event.is_set(), timeout=QT_TIMEOUT_STATUS)