from __future__ import annotations

"""
At this level of test case we not use QApplicaiton and processEvent for test anymore, instead we use pip install pytest-qt and qbot wait.
"""
import importlib.util
import json
from pathlib import Path
import threading
import time

import pytest

from can_service.chal.base import ChannelState
from can_service.events import ReceiverControlEvent, ReceiverControlType, ReplayStatusEvent, ReplayStatusType, SendStatusEvent, SendStatusType
from can_service.srv_if import get_can_service_facade
from file_service.record_id import RecordId
from file_service.srv_if import get_file_service
from can_service.unit_test.can_srv__UT import _parse_log_to_record_id

TIMEOUT_STATUS = 0.5 # Time for the reponse status from worker since got the command

RECEIVER_REPORT_DIR = CAN_ROOT / "src" / "can_service" / "receive" / "data"
SENDER_REPORT_DIR = CAN_ROOT / "src" / "can_service" / "send" / "data"
REPLAY_REPORT_DIR = CAN_ROOT / "src" / "can_service" / "replay" / "data"

def _is_number_token(token: str) -> bool:
	text = str(token).strip()
	if not text:
		return False
	if text.count(".") > 1:
		return False
	return text.replace(".", "", 1).isdigit()


def _extract_pattern_tokens(pattern: str) -> list[str]:
	return [part for part in str(pattern or "").split("_") if part and not _is_number_token(part)]

"""
Pattern syntax:
    RC<ch>              = REGISTER_CHANNEL, e.g., RC0, RC1
    UC<ch>              = UNREGISTER_CHANNEL
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

SEND_SENARIOS = [
    (
        "A0:100:1_RA_PA", # Pattern
        [
            SendCmdType.ADD, #A0:100
            SendCmdType.RESUME_ALL, #RA
            SendCmdType.PAUSE_ALL, #PA
        ],
        ["Add message 0x100 with period 1ms and send to channel idx 0, resume all and then pause all"], # Description
    ),
    (
        "A0:100:1_UP0:100:0.02_P0:100_R0:100_RM0:100_CLR",
        [
            SendCmdType.ADD, #A0:100
            SendCmdType.UPDATE_PERIOD, #UP0:100:0.02
            SendCmdType.PAUSE, #P0:100
            SendCmdType.RESUME, #R0:100
            SendCmdType.REMOVE, #RM0:100
            SendCmdType.CLEAR, #CLR
        ],
        [],
    ),
]
@pytest.mark.parametrize(
)
def test_IT_PATTERN_SEND(can_service, expected_tokens: set[str]) -> None:
	can_srv = can_service
	file_srv = get_file_service()
	snapshot = can_srv.get_channels_snapshot()
	acquired = next((info for info in snapshot.values() if info.state == ChannelState.ACQUIRED), None)
	assert acquired is not None, "no ACQUIRED channel found; reuse existing setup from can_srv__UT.py before running IT"
	acquired_channel_idx = int(acquired.channel_idx)

	entry_1 = file_srv.parse_line("0.000001 1 6A1 Tx d 8 01 02 03 04 05 06 07 08")
	entry_1.channel = str(acquired_channel_idx)
	entry_2 = file_srv.parse_line("0.000001 1 6A2 Tx d 8 11 12 13 14 15 16 17 18")
	entry_2.channel = str(acquired_channel_idx)

	added_1 = threading.Event()
	added_2 = threading.Event()
	can_srv.subscribe(
		SendStatusEvent,
		lambda event: (
			event.channel_id == acquired_channel_idx
			and event.can_id == 0x6A1
			and event.status is SendStatusType.ADDED
			and added_1.set()
		),
	)
	can_srv.subscribe(
		SendStatusEvent,
		lambda event: (
			event.channel_id == acquired_channel_idx
			and event.can_id == 0x6A2
			and event.status is SendStatusType.ADDED
			and added_2.set()
		),
	)

	sender_report_since = time.time()
	assert can_srv.send_msg_loop(entry_1, initial_periodic=0.02, timeout_s=10.0) is True
	assert can_srv.send_msg_loop(entry_2, initial_periodic=0.02, timeout_s=10.0) is True
	assert added_1.wait(timeout=3.0)
	assert added_2.wait(timeout=3.0)
	assert can_srv.pause_all() is True
