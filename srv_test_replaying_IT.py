from __future__ import annotations

import time

import pytest
from fixture import CANService, FileService, TestServices
# pytest_plugins = ("srv_fixture",)

TIMEOUT_STATUS = 0.5
TIMEOUT_RUNTEST = 30.0
PROJECT_ROOT = "/home/gnar911/Desktop/20260516_JOBS_INSPECTOR/project/IT_test/"

@pytest.mark.parametrize(
    "source_file",
    [
        PROJECT_ROOT + "cs_test/data_test/2025-02-11_11-14-53_仕様情報切替 1.asc",
        PROJECT_ROOT + "cs_test/data_test/2025-02-11_11-14-53_仕様情報切替 1_x10.asc",
    ],
)
def test_30_replay(all_service: tuple[CANService, FileService, TestServices], source_file: str, qtbot) -> None:
    can_srv, file_srv, vm = all_service
    assert file_srv.parse_log(source_file) is True
    assert vm.parser_done_event.wait(timeout=TIMEOUT_RUNTEST), "Parser did not finish"

    assert not vm.parser_failed_event.is_set()
    assert vm.parser_record_id is not None
    record_id = vm.parser_record_id

    assert can_srv.start_replay(record_id) is True
    assert vm.replay_source_set_event.wait(timeout=TIMEOUT_STATUS)
    assert vm.replay_started_event.wait(timeout=TIMEOUT_STATUS), "STARTED not received"
    assert vm.rpl_cycle_finished_event.wait_n(1, TIMEOUT_RUNTEST)
    assert vm.rpl_finished_event.wait(timeout=TIMEOUT_RUNTEST)

@pytest.mark.parametrize(
    "source_file",
    [
        PROJECT_ROOT + "cs_test/data_test/2025-02-11_11-14-53_仕様情報切替 1.asc",
        # PROJECT_ROOT + "cs_test/data_test/2025-02-11_11-14-53_仕様情報切替 1_x10.asc",
    ],
)
def test_31_pause_replay(all_service: tuple[CANService, FileService, TestServices], source_file: str, qtbot) -> None:
    can_srv, file_srv, vm = all_service
    assert file_srv.parse_log(source_file) is True
    assert vm.parser_done_event.wait(timeout=TIMEOUT_RUNTEST), "Parser did not finish"
    assert not vm.parser_failed_event.is_set()
    assert vm.parser_record_id is not None
    record_id = vm.parser_record_id

    assert can_srv.start_replay(record_id) is True
    assert vm.replay_started_event.wait(timeout=TIMEOUT_STATUS), "STARTED not received"

    qtbot.wait(1000)
    assert can_srv.pause_replay() is True
    assert vm.replay_paused_event.wait(timeout=TIMEOUT_STATUS), "PAUSED not received"

    qtbot.wait(1000)
    assert can_srv.stop_replay() is True
    assert vm.replay_stopped_event.wait(timeout=TIMEOUT_STATUS), "STOPPED not received"


@pytest.mark.parametrize(
    "source_file",
    [
        PROJECT_ROOT + "cs_test/data_test/2025-02-11_11-14-53_仕様情報切替 1.asc",
        # PROJECT_ROOT + "cs_test/data_test/2025-02-11_11-14-53_仕様情報切替 1_x10.asc",
    ],
)
def test_32_resume_replay(all_service: tuple[CANService, FileService, TestServices], source_file: str, qtbot) -> None:
    can_srv, file_srv, vm = all_service
    assert file_srv.parse_log(source_file) is True
    assert vm.parser_done_event.wait(timeout=TIMEOUT_RUNTEST), "Parser did not finish"
    assert not vm.parser_failed_event.is_set()
    assert vm.parser_record_id is not None
    record_id = vm.parser_record_id

    assert can_srv.start_replay(record_id) is True
    assert vm.replay_started_event.wait(timeout=TIMEOUT_STATUS), "STARTED not received"

    qtbot.wait(1000)
    assert can_srv.pause_replay() is True
    assert vm.replay_paused_event.wait(timeout=TIMEOUT_STATUS), "PAUSED not received"

    qtbot.wait(1000)
    assert can_srv.resume_replay() is True
    assert vm.replay_resumed_event.wait(timeout=TIMEOUT_STATUS), "RESUMED not received"

    qtbot.wait(1000)
    assert can_srv.stop_replay() is True
    assert vm.replay_stopped_event.wait(timeout=TIMEOUT_STATUS), "STOPPED not received"

@pytest.mark.parametrize(
    "source_file",
    [
        PROJECT_ROOT + "cs_test/data_test/2025-02-11_11-14-53_仕様情報切替 1.asc",
        # PROJECT_ROOT + "cs_test/data_test/2025-02-11_11-14-53_仕様情報切替 1_x10.asc",
    ],
)
def test_33_stop_replay(all_service: tuple[CANService, FileService, TestServices], source_file: str, qtbot) -> None:
    can_srv, file_srv, vm = all_service
    assert file_srv.parse_log(source_file) is True
    assert vm.parser_done_event.wait(timeout=TIMEOUT_RUNTEST), "Parser did not finish"

    assert not vm.parser_failed_event.is_set()
    assert vm.parser_done_event.is_set()
    assert vm.parser_record_id is not None
    record_id = vm.parser_record_id

    assert can_srv.start_replay(record_id) is True
    assert vm.replay_started_event.wait(timeout=TIMEOUT_STATUS), "STARTED not received"

    qtbot.wait(1000)
    assert can_srv.stop_replay() is True
    assert vm.replay_stopped_event.wait(timeout=TIMEOUT_STATUS), "STOPPED not received"
