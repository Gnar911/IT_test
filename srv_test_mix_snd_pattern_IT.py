from __future__ import annotations

"""
At this level of test case we not use QApplicaiton and processEvent for test anymore, instead we use pip install pytest-qt and qbot wait.
"""
from dataclasses import dataclass
import time
from typing import Any
from collections import Counter

import pytest
from can_service.send.snd_contract import *
from file_service.module.fs_core import ParsedEntry
from fixture import CANService, FileService, TestServices, all_service
from lw.evt_loop_trace import SchedulerGraphBuilder
from can_service.srv_status import CommandEvent

TIMEOUT_STATUS = 0.5 # Time for the reponse status from worker since got the command
MIN_COMMAND_INTERVAL = 2.0 # Time for sparing between 2 commands
MAX_COMMAND_INTERVAL = 8.0
TIMEOUT_RUN = 5.0 #Default time out for infinite run case

@dataclass
class MsgBuilder:
	"""Build ParsedEntry lazily after fixtures are ready."""
	can_id: int
	period_s: float = 0.02
	data_hex: str = "01 02 03 04 05 06 07 08"

	def build(self, file_srv: FileService) -> ParsedEntry:
		entry = file_srv.parse_line(
			f"0.000001 0 {self.can_id:03X} Tx d 8 {self.data_hex}"
		)
		return entry


"""
Pattern syntax:
    A<ch>:<id>:<p>      = ADD message with period ms, e.g., A0:100:1, A1:0x200:3
    RM<ch>:<id>         = REMOVE message
    CLR                 = CLEAR
    R<ch>:<id>          = RESUME (single message)
    P<ch>:<id>          = PAUSE (single message)
    RA                  = RESUME_ALL
    PA                  = PAUSE_ALL
    UP<ch>:<id>:<p>     = UPDATE_PERIOD, e.g., UP0:100:0.01
    UD<ch>:<id>:<data>  = UPDATE_DATA, e.g., UD0:100:DEADBEEF11
"""

SEND_SCENARIOS = [
    (
        "TC001",
        [
            (SndAdd, MsgBuilder(0x123, period_s=1.0)),
        ],
    ),
    (
        # "TC002",
        # [
        #     (SndAdd, MsgBuilder(0x123, period_s=1.0)),
        #     (SndPause, MsgBuilder(0x123)),
        #     (SndResume, MsgBuilder(0x123)),
        # ],
    ),
]


@pytest.mark.parametrize("tc_name, scenario", SEND_SCENARIOS)
def test_IT_PATTERN_SEND(
    all_service: tuple[CANService, FileService, TestServices],
    qtbot,
	tc_name: str,
    scenario: list[tuple[type[CommandEvent], MsgBuilder]],
) -> None:
	
	SchedulerGraphBuilder.suffix = tc_name
	print(f"Running {tc_name}")

	can_srv, file_srv, vm = all_service

	vm.start_track_progress_thread()
	assert file_srv.start_recording() is True
	qtbot.waitUntil(lambda: vm.recorder_active_event.is_set(), timeout=int(TIMEOUT_STATUS * 1000))

	device = vm.acquired_devices[0]

	# Simple factory: scenario stores command class, build concrete runtime args after fixture acquisition.
	commands: list[tuple[type[CommandEvent], ParsedEntry, float]] = []
	for cmd_type, builder in scenario:
		entry = builder.build(file_srv)
		commands.append((cmd_type, entry, float(builder.period_s)))

	counter = Counter()
	for idx, (cmd_type, entry, period_s) in enumerate(commands):
		counter[cmd_type] += 1

		if cmd_type is SndAdd:
			assert can_srv.send_msg_loop(device, entry, initial_periodic=period_s) is True
			vm.snd_add_event.wait_n(counter[SndAdd])
			
		elif cmd_type is SndPause:
			assert can_srv.pause_msg(device, entry) is True
			vm.snd_pause_event.wait_n(counter[SndPause])

		elif cmd_type is SndResume:
			assert can_srv.resume_msg(device, entry) is True
			vm.snd_resume_event.wait_n(counter[SndResume])

		elif cmd_type is SndUpdatePeriod:
			assert can_srv.update_periodic(device, entry, period_s) is True
			vm.snd_update_period_event.wait_n(counter[SndUpdatePeriod])

		elif cmd_type is SndRemove:
			assert can_srv.remove_msg(device, entry) is True
			vm.snd_remove_event.wait_n(counter[SndRemove])

		elif cmd_type is SndClear:
			assert can_srv.clear() is True
			vm.snd_clear_event.wait()

		else:
			pytest.fail(f"unsupported send command in scenario: {cmd_type}")

		if idx < len(commands) - 1 and MIN_COMMAND_INTERVAL > 0:
			time.sleep(MIN_COMMAND_INTERVAL)

	qtbot.wait(3000)



	assert file_srv.stop_recording() is True
	qtbot.waitUntil(lambda: vm.recorder_stopped_event.is_set(), timeout=int(TIMEOUT_STATUS * 1000))


    
