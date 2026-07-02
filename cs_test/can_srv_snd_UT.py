from __future__ import annotations

import pytest

from can_service.srv_if import CANService
from fixture import CanServiceVM
from file_service.srv_if import get_file_service

pytest_plugins = ["fixture"]

TIMEOUT_STATUS = 0.5

@pytest.mark.parametrize(
	"device_id, text_line, periodic_s",
	[
		("vcan0", "0.000001 1 123 Tx d 8 01 02 03 04 05 06 07 08", 1.0),
	],
)
def test_40_send_msg_loop(acquire_vcan_devices: tuple[CANService, CanServiceVM], device_id: str, text_line: str, periodic_s: float, qtbot) -> None:

	can_srv, vm = acquire_vcan_devices
	file_srv = get_file_service()

	entry = file_srv.parse_line(text_line)
	acquired_device_info = vm.acquired_devices[0]

	assert can_srv.send_msg_loop(acquired_device_info, entry, initial_periodic=periodic_s) is True
	assert vm.snd_add_event.wait(timeout=TIMEOUT_STATUS)

	qtbot.wait(5000)


def test_42_pause_msg(acquire_vcan_devices: tuple[CANService, CanServiceVM], qtbot) -> None:
	can_srv, vm = acquire_vcan_devices
	file_srv = get_file_service()
	# use the acquired CANDeviceInfo provided by the fixture
	acquired_device_info = vm.acquired_devices[0]
	can_id = 0x331

	entry = file_srv.parse_line("0.000001 1 331 Tx d 8 01 02 03 04 05 06 07 08")

	assert can_srv.send_msg_loop(acquired_device_info, entry, initial_periodic=0.02) is True
	assert vm.snd_add_event.wait(timeout=TIMEOUT_STATUS)
	qtbot.wait(1000)
	assert can_srv.pause_msg(acquired_device_info, entry) is True
	assert vm.snd_pause_event.wait(timeout=TIMEOUT_STATUS)

	assert can_srv.clear() is True


def test_43_pause_all(acquire_vcan_devices: tuple[CANService, CanServiceVM], qtbot) -> None:
	can_srv, vm = acquire_vcan_devices
	file_srv = get_file_service()
	acquired_device_info = vm.acquired_devices[0]

	entry_1 = file_srv.parse_line("0.000001 1 341 Tx d 8 01 02 03 04 05 06 07 08")
	entry_2 = file_srv.parse_line("0.000001 1 342 Tx d 8 01 02 03 04 05 06 07 08")

	assert can_srv.send_msg_loop(acquired_device_info, entry_1, initial_periodic=0.02) is True
	assert can_srv.send_msg_loop(acquired_device_info, entry_2, initial_periodic=0.02) is True
	assert vm.snd_add_event.wait(timeout=TIMEOUT_STATUS)
	qtbot.wait(1000)
	assert can_srv.pause_msg(acquired_device_info, entry_1) is True
	assert can_srv.pause_msg(acquired_device_info, entry_2) is True
	assert vm.snd_pause_event.wait(timeout=TIMEOUT_STATUS)

	assert can_srv.clear() is True


def test_44_resume_msg(acquire_vcan_devices: tuple[CANService, CanServiceVM], qtbot) -> None:
	can_srv, vm = acquire_vcan_devices
	file_srv = get_file_service()
	acquired_device_info = vm.acquired_devices[0]
	can_id = 0x351

	entry = file_srv.parse_line("0.000001 1 351 Tx d 8 01 02 03 04 05 06 07 08")

	assert can_srv.send_msg_loop(acquired_device_info, entry, initial_periodic=0.02) is True
	assert vm.snd_add_event.wait(timeout=TIMEOUT_STATUS)
	qtbot.wait(1000)

	assert can_srv.pause_msg(acquired_device_info, entry) is True
	assert vm.snd_pause_event.wait(timeout=TIMEOUT_STATUS)

	assert can_srv.resume_msg(acquired_device_info, entry) is True
	assert vm.snd_resume_event.wait(timeout=TIMEOUT_STATUS)

	assert can_srv.clear() is True


def test_45_resume_all(acquire_vcan_devices: tuple[CANService, CanServiceVM], qtbot) -> None:
	can_srv, vm = acquire_vcan_devices
	file_srv = get_file_service()
	acquired_device_info = vm.acquired_devices[0]

	entry_1 = file_srv.parse_line("0.000001 1 361 Tx d 8 01 02 03 04 05 06 07 08")
	entry_2 = file_srv.parse_line("0.000001 1 362 Tx d 8 01 02 03 04 05 06 07 08")

	assert can_srv.send_msg_loop(acquired_device_info, entry_1, initial_periodic=0.02) is True
	qtbot.wait(1000)
	assert can_srv.send_msg_loop(acquired_device_info, entry_2, initial_periodic=0.02) is True
	assert vm.snd_add_event.wait(timeout=TIMEOUT_STATUS)
	qtbot.wait(1000)
	assert can_srv.pause_msg(acquired_device_info, entry_1) is True
	assert can_srv.pause_msg(acquired_device_info, entry_2) is True
	assert vm.snd_pause_event.wait(timeout=TIMEOUT_STATUS)

	qtbot.wait(1000)
	assert can_srv.resume_msg(acquired_device_info, entry_1) is True
	assert can_srv.resume_msg(acquired_device_info, entry_2) is True
	assert vm.snd_resume_event.wait(timeout=TIMEOUT_STATUS)
	assert can_srv.clear() is True


def test_46_remove_msg(acquire_vcan_devices: tuple[CANService, CanServiceVM], qtbot) -> None:
	can_srv, vm = acquire_vcan_devices
	file_srv = get_file_service()
	acquired_device_info = vm.acquired_devices[0]
	can_id = 0x371

	entry = file_srv.parse_line("0.000001 1 371 Tx d 8 01 02 03 04 05 06 07 08")

	assert can_srv.send_msg_loop(acquired_device_info, entry, initial_periodic=0.02) is True
	assert vm.snd_add_event.wait(timeout=TIMEOUT_STATUS)
	qtbot.wait(1000)
	assert can_srv.remove_msg(acquired_device_info, entry) is True
	assert vm.snd_remove_event.wait(timeout=TIMEOUT_STATUS)

	assert can_srv.clear() is True


def test_47_clear(acquire_vcan_devices: tuple[CANService, CanServiceVM], qtbot) -> None:
	can_srv, vm = acquire_vcan_devices
	file_srv = get_file_service()
	acquired_device_info = vm.acquired_devices[0]

	entry_1 = file_srv.parse_line("0.000001 1 381 Tx d 8 01 02 03 04 05 06 07 08")
	entry_2 = file_srv.parse_line("0.000001 1 382 Tx d 8 01 02 03 04 05 06 07 08")

	assert can_srv.send_msg_loop(acquired_device_info, entry_1, initial_periodic=0.02) is True
	qtbot.wait(1000)
	assert can_srv.send_msg_loop(acquired_device_info, entry_2, initial_periodic=0.02) is True
	assert vm.snd_add_event.wait(timeout=TIMEOUT_STATUS)
	qtbot.wait(1000)
	assert can_srv.clear() is True
	assert vm.snd_clear_event.wait(timeout=TIMEOUT_STATUS)


def test_48_update_periodic(acquire_vcan_devices: tuple[CANService, CanServiceVM], qtbot) -> None:
	can_srv, vm = acquire_vcan_devices
	file_srv = get_file_service()
	acquired_device_info = vm.acquired_devices[0]
	can_id = 0x391

	entry = file_srv.parse_line("0.000001 1 391 Tx d 8 01 02 03 04 05 06 07 08")

	assert can_srv.send_msg_loop(acquired_device_info, entry, initial_periodic=0.02) is True
	assert vm.snd_add_event.wait(timeout=TIMEOUT_STATUS)
	qtbot.wait(1000)
	assert can_srv.update_periodic(acquired_device_info, entry, 0.03) is True
	assert vm.snd_update_period_event.wait(timeout=TIMEOUT_STATUS)

	assert can_srv.clear() is True
