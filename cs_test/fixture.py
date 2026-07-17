from __future__ import annotations

"""
At this level of test case we not use QApplicaiton and processEvent for test anymore, instead we use pip install pytest-qt and qbot wait.
"""
from pathlib import Path
import subprocess
import time
from typing import Generator
import pytest
from can_service.chal.base import CANDeviceInfo
from can_service.chal.device_type import CANDeviceType
import can_service.srv_if as can_service_srv_if
from can_service.srv_if import CANService, get_can_service_facade
import threading
from lw.logger_setup import LOG, setup_logger
from cs_test.mock_vm import *
from canapp.vm.log_viewmodel import LogViewModel

def reset_events(events: list[threading.Event]) -> None:
	for event in events:
		event.clear()

class CanServiceVM(ReplayStatusVM, 
				   ReceiverVM,  
				   ScannerVM, 
					#LogViewModel,
				   SendStatusVM):
	def __init__(self):
		ReplayStatusVM.__init__(self)
		ReceiverVM.__init__(self)
		ScannerVM.__init__(self)
		#LogViewModel.__init__(self)
		SendStatusVM.__init__(self)

	def reset(self):
		ReplayStatusVM.reset(self)
		ReceiverVM.reset(self)
		#LogViewModel.reset(self)
		ScannerVM.reset(self)
		SendStatusVM.reset(self)

TIMEOUT_SCAN = 2.0
TIMEOUT_STATUS = 0.5

""" #NOTE: Override this fixture at your conftest.py test layer"""
@pytest.fixture
def app_vm() -> CanServiceVM:
    return CanServiceVM()

""" 20260628: #NOTE This cause the hardcode vm CanSerivceVM -> pass it as the fixture and overloading at re-use layer test"""
@pytest.fixture(scope="function")
def can_service(app_vm: CanServiceVM) -> Generator[tuple[CANService, CanServiceVM], None, None]:
	setup_logger(env="DEV", backup_count=30)
	srv = get_can_service_facade()
	vm = app_vm

	vm.reset()
	srv.start()
	registered_callbacks = [
		vm.on_replay_status,
		vm.on_send_status,
		vm.on_scan_status,
		vm.on_receiver_status,
	]

	for callback in registered_callbacks:
		srv.subscribe(callback)

	try:
		yield srv, vm
	finally:
		vm.reset()
		srv.unsubscribe_all()

		print("Stop service")
		srv.stop()

@pytest.fixture(scope="function")
def acquired_real_devices(can_service, request):
	can_srv, vm = can_service
	scenario_param = getattr(request, "param", None)
	if scenario_param is None:
		expected_by_vendor: dict[CANDeviceType, int] = {}
	elif isinstance(scenario_param, dict):
		expected_by_vendor = scenario_param
	else:
		raise AssertionError(f"acquired_real_devices expects dict param, got {type(scenario_param)!r}")

	def _count_by_vendor(devices: list[CANDeviceInfo]) -> dict[CANDeviceType, int]:
		counts: dict[CANDeviceType, int] = {}
		for info in devices:
			counts[info.vendor] = counts.get(info.vendor, 0) + 1
		return counts

	def _has_expected(counts: dict[CANDeviceType, int]) -> bool:
		for vendor, expected_count in expected_by_vendor.items():
			if counts.get(vendor, 0) < int(expected_count):
				return False
		return True

	deadline = time.time() + (TIMEOUT_SCAN)
	devices: list[CANDeviceInfo] = []
	counts: dict[CANDeviceType, int] = {}
	while time.time() < deadline:
		devices = can_srv.get_device_list()
		counts = _count_by_vendor(devices)
		if _has_expected(counts):
			break
		vm.plugged_event.wait(0.2)

	for vendor, expected_count in expected_by_vendor.items():
		observed_count = counts.get(vendor, 0)
		if observed_count < int(expected_count):
			pytest.skip(f"Requires {expected_count} {vendor.name}, found {observed_count}")

	acquired_handles: list[str] = []
	acquired_infos: list[CANDeviceInfo] = []
	vendor_acquired: dict[CANDeviceType, int] = {}

	for info in sorted(devices, key=lambda d: str(d.device_id)):
		device_id = str(info.device_id)
		vendor = info.vendor
		expected_for_vendor = expected_by_vendor.get(vendor)
		if expected_for_vendor is not None and vendor_acquired.get(vendor, 0) >= int(expected_for_vendor):
			continue

		assert can_srv.acquire(info) is True
		assert vm.acquired_event.wait(TIMEOUT_SCAN)
		acquired_handles.append(device_id)
		acquired_infos.append(info)
		vendor_acquired[vendor] = vendor_acquired.get(vendor, 0) + 1

	assert acquired_handles, "No test channels were acquired"

	yield can_srv, vm 

	for info in acquired_infos:
		assert can_srv.release(info) is True
		assert vm.released_event.wait(TIMEOUT_SCAN)


@pytest.fixture(
	scope="function",
	params=[
		{CANDeviceType.SOCKETCAN: 2},
		#{CANDeviceType.SOCKETCAN: 4},
	],
)
def acquire_vcan_devices(
	can_service: tuple[CANService, CanServiceVM],
	request,
)-> Generator[tuple[CANService, CanServiceVM], None, None]:
	can_srv, vm = can_service
	expected = getattr(request, "param", None)
	vcan_count = int(expected.get(CANDeviceType.SOCKETCAN, 0))

	# set up vcan devices
	socket_script_dir = Path(can_service_srv_if.__file__).resolve().parent / "chal" / "socket"
	result = subprocess.run(
		["bash", str(socket_script_dir / "bring_down_all_vcan.sh")],
		capture_output=True,
		text=True,
	)
	assert result.returncode == 0, result.stderr or result.stdout

	for i in range(vcan_count):
		result = subprocess.run(
			["bash", str(socket_script_dir / f"vcan{i}_up.sh")],
			capture_output=True,
			text=True,
		)
		assert result.returncode == 0, result.stderr or result.stdout

	""" NOTE: this is the senarios for the fixture set up test cases, not the real application lock/inlock channel senarios test"""
	for i in range(vcan_count):
		assert vm.plugged_event.wait(TIMEOUT_SCAN*5)

	for i in range(len(vm.available_device)):
		assert can_srv.acquire(vm.available_device[i]) is True
		assert vm.acquired_event.wait(TIMEOUT_STATUS)
		assert vm.snd_device_acquired_event.wait(TIMEOUT_STATUS)
		assert vm.rcv_device_acquired_event.wait(TIMEOUT_STATUS)
		assert vm.rpl_device_acquired_event.wait(TIMEOUT_STATUS)
		vm.acquired_devices.append(vm.available_device[i])
	
	assert len(vm.acquired_devices) == vcan_count

	yield can_srv, vm

	acquires = vm.acquired_devices
	# iterate over a copy since releasing removes items from the list
	for dev in list(acquires):
		can_srv.release(dev)
		assert vm.released_event.wait(TIMEOUT_STATUS)
		assert vm.snd_device_unacquired_event.wait(TIMEOUT_STATUS)
		assert vm.rcv_device_unacquired_event.wait(TIMEOUT_STATUS)
		assert vm.rpl_device_unacquired_event.wait(TIMEOUT_STATUS)
		vm.acquired_devices.remove(dev)

	assert len(vm.acquired_devices) == 0

	# Bring down vcan devices
	result = subprocess.run(
		["bash", str(socket_script_dir / "bring_down_all_vcan.sh")],
		capture_output=True,
		text=True,
	)

	# Wait for can device to be bringdown
	for i in range(vcan_count):
		assert vm.unplugged_event.wait(TIMEOUT_SCAN)

	assert result.returncode == 0, result.stderr or result.stdout