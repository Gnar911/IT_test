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
from dataclasses import dataclass, field
import threading
from lw.logger_setup import LOG, setup_logger

from can_service.scan.scan_contract import (
	ScanDevicePluggedStatus,
	ScanDeviceUnpluggedStatus,
	ScanChannelAcquiredStatus,
	ScanChannelReleasedStatus,
)
from can_service.replay.rpl_contract import (
	ReplayCmdType,
	ReplayInterruptCmdType,
	ReplaySetFilterMsg,
	ReplaySetLoop,
	ReplaySetRepeat,
	ReplaySetSource,
	ReplaySetTimescope,
	ReplaySetChannelMapping,
	RplDeviceAccquired,
	RplDeviceUnaccquired,
	RplFinished,
	RplCycleFinished,
)
from can_service.receive.rcv_contract import (
	AddGatewayRoute,
	RemoveGatewayRoute,
    DeviceAccquired,
    DeviceUnaccquired,
)
from can_service.send.snd_contract import (
	SndAdd,
	SndClear,
	SndPause,
	SndRemove,
	SndResume,
	SndUpdateData,
	SndUpdatePeriod,
	SndDeviceAccquired,
	SndDeviceUnaccquired,
)
from can_service.srv_status import ResponseACK, NotificationEvent

def reset_events(events: list[threading.Event]) -> None:
	for event in events:
		event.clear()

""" BUT: this is not good if 2 events came nearly at the same time, then the clear will swallow them
	-> Boolean event like threading.Event can not be used to simulate the Event Edge Trigger

	Event:

	set()        state = 1
	set()        state = 1   # second event lost

	vs.

	Semaphore:

	release()    count = 1
	release()    count = 2   # second event preserved
"""
# class EdgeTriggerEvent(threading.Event):
#     def wait(self, timeout=None):
#         result = super().wait(timeout)
#         if result:
#             self.clear()
#         return result
class EdgeTriggerEvent:
	def __init__(self):
		self._sem = threading.Semaphore(0)

	def set(self):
		self._sem.release()

	def wait(self, timeout=None):
		return self._sem.acquire(timeout=timeout)

	def wait_n(self, count: int, timeout=None) -> bool:
		deadline = None if timeout is None else time.monotonic() + timeout

		for _ in range(count):
			if deadline is None:
				self._sem.acquire()
			else:
				remaining = deadline - time.monotonic()
				if remaining <= 0:
					return False
				if not self._sem.acquire(timeout=remaining):
					return False

		return True

	def clear(self):
		while self._sem.acquire(blocking=False):
			pass

@dataclass
class ReplayStatusVM:
	replay_started_event: threading.Event = field(default_factory=threading.Event)
	replay_paused_event: threading.Event = field(default_factory=threading.Event)
	replay_resumed_event: threading.Event = field(default_factory=threading.Event)
	replay_stopped_event: threading.Event = field(default_factory=threading.Event)
	replay_source_set_event: threading.Event = field(default_factory=threading.Event)
	replay_source_unset_event: threading.Event = field(default_factory=threading.Event)
	replay_channel_mapping_event: threading.Event = field(default_factory=threading.Event)
	replay_loop_set_event: threading.Event = field(default_factory=threading.Event)
	replay_repeat_set_event: threading.Event = field(default_factory=threading.Event)
	replay_filter_set_event: threading.Event = field(default_factory=threading.Event)
	replay_timescope_set_event: threading.Event = field(default_factory=threading.Event)
	rpl_device_acquired_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	rpl_device_unacquired_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	rpl_finished_event: threading.Event = field(default_factory=threading.Event)
	rpl_cycle_finished_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)

	@property
	def started_event(self):
		return self.replay_started_event

	@property
	def paused_event(self):
		return self.replay_paused_event

	@property
	def resumed_event(self):
		return self.replay_resumed_event

	@property
	def stopped_event(self):
		return self.replay_stopped_event

	@property
	def source_set_event(self):
		return self.replay_source_set_event

	@property
	def source_unset_event(self):
		return self.replay_source_unset_event

	@property
	def channel_registered_event(self):
		return self.replay_channel_mapping_event

	@property
	def channel_unregistered_event(self):
		return self.replay_channel_mapping_event

	@property
	def loop_set_event(self):
		return self.replay_loop_set_event

	@property
	def repeat_set_event(self):
		return self.replay_repeat_set_event

	@property
	def filter_set_event(self):
		return self.replay_filter_set_event

	@property
	def timescope_set_event(self):
		return self.replay_timescope_set_event

	def on_replay_status(self, event: object) -> None:
		# Notification events (non-ACK) such as replay finished are delivered
		if isinstance(event, NotificationEvent):
			if isinstance(event.evt, RplFinished):
				self.rpl_finished_event.set()
				return
			if isinstance(event.evt, RplCycleFinished):
				self.rpl_cycle_finished_event.set()
				return

		if not isinstance(event, ResponseACK):
			return

		LOG.info("on_replay_status event=%s cmd_type=%s", type(event).__name__, event.cmd_type)
		if event.cmd_type == ReplayCmdType.START:
			self.started_event.set()
			return
		if event.cmd_type == ReplayCmdType.RESUME:
			self.resumed_event.set()
			return
		if event.cmd_type == ReplayInterruptCmdType.PAUSE:
			self.paused_event.set()
			return
		if event.cmd_type == ReplayInterruptCmdType.STOP:
			self.stopped_event.set()
			return
		if event.cmd_type == ReplayInterruptCmdType.UNSET_SOURCE:
			self.source_unset_event.set()
			return

		key_cls = event.cmd_type
		ACK_EVENT_MAP = {
			ReplaySetSource: self.source_set_event,
			ReplaySetChannelMapping: self.channel_registered_event,
			ReplaySetLoop: self.loop_set_event,
			ReplaySetRepeat: self.repeat_set_event,
			ReplaySetFilterMsg: self.filter_set_event,
			ReplaySetTimescope: self.timescope_set_event,
			RplDeviceAccquired: self.rpl_device_acquired_event,
			RplDeviceUnaccquired: self.rpl_device_unacquired_event,
		}
		evt = ACK_EVENT_MAP.get(key_cls)
		if evt is not None:
			evt.set()

	def reset(self) -> None:
		reset_events([
			self.replay_started_event,
			self.replay_paused_event,
			self.replay_resumed_event,
			self.replay_stopped_event,
			self.replay_source_set_event,
			self.replay_source_unset_event,
			self.replay_channel_mapping_event,
			self.replay_loop_set_event,
			self.replay_repeat_set_event,
			self.replay_filter_set_event,
			self.replay_timescope_set_event,
			self.rpl_finished_event,
		])

		self.rpl_device_acquired_event.clear()
		self.rpl_device_unacquired_event.clear()
		self.rpl_cycle_finished_event.clear()


@dataclass
class SendStatusVM:
	snd_add_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	snd_clear_event: threading.Event = field(default_factory=threading.Event)
	snd_remove_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	snd_pause_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	snd_resume_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	snd_update_period_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	snd_update_data_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	snd_device_acquired_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	snd_device_unacquired_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	# send_status_trace: list[object] = field(default_factory=list)

	# @property
	# def status_trace(self):
	# 	return self.send_status_trace

	def on_send_status(self, event: object) -> None:
		#self.send_status_trace.append(event)
		if not isinstance(event, ResponseACK):
			return
		key_cls = event.cmd_type
		ACK_EVENT_MAP = {
			SndAdd: self.snd_add_event,
			SndClear: self.snd_clear_event,
			SndRemove: self.snd_remove_event,
			SndPause: self.snd_pause_event,
			SndResume: self.snd_resume_event,
			SndUpdatePeriod: self.snd_update_period_event,
			SndUpdateData: self.snd_update_data_event,
			SndDeviceAccquired: self.snd_device_acquired_event,
			SndDeviceUnaccquired: self.snd_device_unacquired_event,
		}
		evt = ACK_EVENT_MAP.get(key_cls)
		if evt is not None:
			evt.set()

	def reset(self) -> None:
		#self.send_status_trace.clear()
		reset_events([
		# 	self.snd_add_event,
			self.snd_clear_event,
			#self.snd_remove_event,
			# self.snd_pause_event,
			# self.snd_resume_event,
			# self.snd_update_period_event,
			# self.snd_update_data_event,
		])
		self.snd_update_period_event.clear()
		self.snd_update_data_event.clear()
		self.snd_resume_event.clear()
		self.snd_pause_event.clear()
		self.snd_remove_event.clear()
		self.snd_add_event.clear()
		self.snd_device_acquired_event.clear()
		self.snd_device_unacquired_event.clear()
	
@dataclass
class ScannerVM:
	plugged_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	unplugged_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	acquired_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	released_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	available_device: list[CANDeviceInfo] = field(default_factory=list)
	acquired_devices: list[CANDeviceInfo] = field(default_factory=list)

	def on_scan_status(self, event: object) -> None:
		#LOG.debug("ScannerVM.on_scan_status called: %s", repr(event))
		if isinstance(event, NotificationEvent):
			if isinstance(event.evt, ScanDevicePluggedStatus):
				# LOG.debug("plugged_event: %s", repr(self.plugged_event))
				self.plugged_event.set()
				payload = event.evt
				self.available_device.append(payload.device_info)
				return
			if isinstance(event.evt, ScanDeviceUnpluggedStatus):
				self.unplugged_event.set()
				payload = event.evt
				self.available_device.append(payload.device_info)
				return

		if isinstance(event, ResponseACK):
			if event.cmd_type == ScanChannelAcquiredStatus:
				self.acquired_event.set()
				return
			if event.cmd_type == ScanChannelReleasedStatus:
				self.released_event.set()
				return

	def reset(self) -> None:
		self.plugged_event.clear()
		self.unplugged_event.clear()
		self.acquired_event.clear()
		self.released_event.clear()
		pass


@dataclass
class ReceiverVM:
	opened_event: threading.Event = field(default_factory=threading.Event)
	closed_event: threading.Event = field(default_factory=threading.Event)
	rcv_device_acquired_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
	rcv_device_unacquired_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)

	def on_receiver_status(self, event: object) -> None:
		if not isinstance(event, ResponseACK):
			return
		key_cls = event.cmd_type
		ACK_EVENT_MAP = {
			AddGatewayRoute: self.opened_event,
			RemoveGatewayRoute: self.closed_event,
			DeviceAccquired: self.rcv_device_acquired_event,
			DeviceUnaccquired: self.rcv_device_unacquired_event,
		}
		evt = ACK_EVENT_MAP.get(key_cls)
		if evt is not None:
			evt.set()

	def reset(self) -> None:
		reset_events([
			self.opened_event,
			self.closed_event,
			self.rcv_device_acquired_event,
			self.rcv_device_unacquired_event,
		])


class CanServiceVM(ReplayStatusVM, ReceiverVM, ScannerVM, SendStatusVM):
	def __init__(self):
		ReplayStatusVM.__init__(self)
		ReceiverVM.__init__(self)
		ScannerVM.__init__(self)
		SendStatusVM.__init__(self)

	def reset(self):
		ReplayStatusVM.reset(self)
		ReceiverVM.reset(self)
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