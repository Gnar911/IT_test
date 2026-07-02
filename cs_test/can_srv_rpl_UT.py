from __future__ import annotations

import pytest
from can_service.srv_if import CANService
from fixture import CanServiceVM

pytest_plugins = ["fixture"]

TIMEOUT_STATUS = 0.5


"""
Performance of status message queue is about < 0.5s
"""
def test_10_set_loop(acquire_vcan_devices: tuple[CANService, CanServiceVM]) -> None:
	can_srv, vm = acquire_vcan_devices

	can_srv.set_loop(True)
	assert vm.loop_set_event.wait(timeout=TIMEOUT_STATUS), "ReplaySetLoop ACK not received"

	# Reset to default so following replay tests remain finite.
	vm.loop_set_event.clear()
	can_srv.set_loop(False)
	assert vm.loop_set_event.wait(timeout=TIMEOUT_STATUS), "ReplaySetLoop ACK not received"


def test_11_set_repeat(acquire_vcan_devices: tuple[CANService, CanServiceVM]) -> None:
	can_srv, vm = acquire_vcan_devices

	can_srv.set_repeat(3)
	assert vm.repeat_set_event.wait(timeout=TIMEOUT_STATUS), "ReplaySetRepeat ACK not received"

	# Reset to default for later replay tests.
	vm.repeat_set_event.clear()
	can_srv.set_repeat(1)
	assert vm.repeat_set_event.wait(timeout=TIMEOUT_STATUS), "ReplaySetRepeat ACK not received"


def test_12_set_msg_id_filter(acquire_vcan_devices: tuple[CANService, CanServiceVM]) -> None:
	can_srv, vm = acquire_vcan_devices
	target_msg_ids = [0x82, 0x215]

	can_srv.set_msg_id_filter(target_msg_ids)
	assert vm.filter_set_event.wait(timeout=TIMEOUT_STATUS), "ReplaySetFilterMsg ACK not received"

	# Reset to default for later replay tests.
	vm.filter_set_event.clear()
	can_srv.set_msg_id_filter([])
	assert vm.filter_set_event.wait(timeout=TIMEOUT_STATUS), "ReplaySetFilterMsg ACK not received"


def test_13_set_time_scope(acquire_vcan_devices: tuple[CANService, CanServiceVM]) -> None:
	can_srv, vm = acquire_vcan_devices
	start_ts = 151.610
	end_ts = 151.620

	can_srv.set_time_scope(start_ts, end_ts)
	assert vm.timescope_set_event.wait(timeout=TIMEOUT_STATUS), "ReplaySetTimescope ACK not received"
