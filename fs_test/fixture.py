from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generator

import pytest
import threading
from multiprocessing import shared_memory
from typing import Generator, Callable
from file_service.application_events import FileServiceStateEvent, ParserStatusEvent, RecorderStatusEvent, \
DecodeStartedEvent, DecodeCompletedEvent, DecodeFileNotFoundEvent, DecodeProgressEvent, DecodeSignalListEvent, DecodeStatusEvent
from file_service.srv_if import FileService, get_file_service
from lw.logger_setup import setup_logger, LOG
from file_service.status import ParserStatus, RecorderStatus
from file_service.status import DecodeStatus
from file_service.record_id import RecordId
from file_service.repository.record import Record
from lw.service.base_service import ServiceState
from PySide6.QtCore import QCoreApplication
import time
from lw.shared_ring_buf import SharedRingBuffer
from file_service.module.fs_core import LogRecord, ParsedEntry
from file_service.recorder.rcd_ring_reader import LogRecordRing
from typing_extensions import deprecated

def reset_events(events: list[threading.Event]) -> None:
	"""Reset a list of threading events after each test case."""
	for event in events:
		event.clear()

class QtEvent(threading.Event):
	def wait(self, timeout: float) -> bool:
		app = QCoreApplication.instance()
		deadline = time.monotonic() + timeout

		while not self.is_set():
			app.processEvents()
			super().wait(0.01)

			if time.monotonic() >= deadline:
				return self.is_set()

		return True

@dataclass
class ServiceStateVM:
	file_state_trace: list[ServiceState] = field(default_factory=list)
	file_running_event: QtEvent = field(default_factory=QtEvent)
	file_stopped_event: QtEvent = field(default_factory=QtEvent)

	def on_file_service_state(self, event: FileServiceStateEvent) -> None:
		state = event.state
		if not isinstance(state, ServiceState):
			raise TypeError(f"FileServiceStateEvent.state must be ServiceState, got {type(state).__name__}")
		self.file_state_trace.append(state)
		if state == ServiceState.RUNNING:
			self.file_running_event.set()
		elif state == ServiceState.STOPPED:
			self.file_stopped_event.set()

	def reset(self) -> None:
		self.file_state_trace.clear()
		reset_events([
			self.file_running_event,
			self.file_stopped_event,
		])


@dataclass
class ParserStatusVM:
	parser_record_id: RecordId | None = None
	parser_idle_event: QtEvent = field(default_factory=QtEvent)
	parser_running_event: QtEvent = field(default_factory=QtEvent)
	parser_done_event: QtEvent = field(default_factory=QtEvent)
	parser_failed_event: QtEvent = field(default_factory=QtEvent)

	@property
	def parse_record_id(self):
		return self.parser_record_id

	@property
	def status_trace(self):
		return self.parser_status_trace

	@property
	def idle_event(self):
		return self.parser_idle_event

	@property
	def running_event(self):
		return self.parser_running_event

	@property
	def done_event(self):
		return self.parser_done_event

	@property
	def failed_event(self):
		return self.parser_failed_event

	def on_parser_status(self, event: ParserStatusEvent) -> None:
		LOG.info(
			"parser_status_event status=%s record_id=%s payload=%s",
			event.status.name,
			event.record_id,
			event.payload,
		)
		status = event.status

		if status == ParserStatus.IDLE:
			self.parser_idle_event.set()
		elif status == ParserStatus.RUNNING:
			self.parser_running_event.set()
		elif status == ParserStatus.DONE:
			if event.record_id is not None:
				self.parser_record_id = event.record_id
			self.parser_done_event.set()
		elif status == ParserStatus.FAILED:
			self.parser_failed_event.set()

	def reset(self) -> None:
		self.parser_record_id = None
		reset_events([
			self.parser_idle_event,
			self.parser_running_event,
			self.parser_done_event,
			self.parser_failed_event,
		])


@dataclass
class RecorderStatusVM:
	record_id: RecordId | None = None
	record: Record | None = None

	""" NOTE: This is the data to be view on the GUI, so there is no point to store all the database on the RAM, only cache the pages"""
	page_entries: list[ParsedEntry] = field(default_factory=list)
	persisted_frames = 0
	recorder_stopped_event: QtEvent = field(default_factory=QtEvent)
	recorder_write_batch_event: QtEvent = field(default_factory=QtEvent)
	recorder_paused_event: QtEvent = field(default_factory=QtEvent)
	recorder_wait_ring_event: QtEvent = field(default_factory=QtEvent)
	recorder_active_event: QtEvent = field(default_factory=QtEvent)
	progress_stop:  QtEvent = field(default_factory=QtEvent)
	#: QtEvent = field(default_factory=QtEvent)

	@property
	def record_id(self):
		return self.record_id

	@property
	def idle_event(self):
		return self.recorder_stopped_event

	@property
	def stopped_event(self):
		return self.recorder_stopped_event

	@property
	def write_batch_event(self):
		return self.recorder_write_batch_event

	@property
	def paused_event(self):
		return self.recorder_paused_event

	@property
	def wait_ring_event(self):
		return self.recorder_wait_ring_event

	@property
	def failed_event(self):
		return self.recorder_stopped_event

	@property
	def active_event(self):
		return self.recorder_active_event

	""" This is ModelView"""
	def on_recorder_status(self, event: RecorderStatusEvent) -> None:
		payload_record_id = event.payload.get("record_id")
		if isinstance(payload_record_id, RecordId):
			self.record_id = payload_record_id
			self.record = get_file_service().get_record(payload_record_id)

			""" The record wrapping the mmap entries are still in growing, so dont take them here"""
			#self.entries = self.record.get_page_from_row_indices(0, 10)

		status = event.status

		if status == RecorderStatus.STOPPED:
			self.recorder_stopped_event.set()
		elif status == RecorderStatus.WRITE_BATCH:
			self.recorder_write_batch_event.set()
			self.recorder_active_event.set()
		elif status == RecorderStatus.PAUSED:
			self.recorder_paused_event.set()
			self.recorder_active_event.set()
		elif status == RecorderStatus.WAIT_RING:
			self.recorder_wait_ring_event.set()
			self.recorder_active_event.set()

	""" This is ModelView"""
	def on_track_progress(self) -> None: 
		while not self.progress_stop.is_set(): 
			if self.record is not None: 
				self.persisted_frames = int(self.record.get_total_lines())	
				LOG.info(self.persisted_frames) 	
				time.sleep(0.1)

	#@deprecated("Use send_msg_loop() instead.")
	def start_track_progress_thread(self):
		self.progress_thread = threading.Thread(
			target=self.on_track_progress,
			daemon=True,
			name="progress-tracker",
		)
		self.progress_thread.start()

	def stop(self):
		self.progress_stop.set()	
		if self.progress_thread is not None:
			self.progress_thread.join(timeout=2.0)

	def reset(self) -> None:
		self.record_id = None
		self.record = None
		reset_events([
			self.recorder_stopped_event,
			self.recorder_write_batch_event,
			self.recorder_paused_event,
			self.recorder_wait_ring_event,
			self.recorder_active_event,
		])

	""" This is ViewModel"""
	def fetch_page(self) -> list[ParsedEntry]:
		if self.record is None:
			return [] 
		self.entries = self.record.get_page_from_row_indices(0, 100)
		return self.entries

@dataclass(slots=True)
class DecodeStatusVM:
	decode_record_id: RecordId | None = None
	decode_started_event: QtEvent = field(default_factory=QtEvent)
	decode_completed_event: QtEvent = field(default_factory=QtEvent)
	decode_file_not_found_event: QtEvent = field(default_factory=QtEvent)
	decode_progress_event: QtEvent = field(default_factory=QtEvent)
	decode_signal_list_event: QtEvent = field(default_factory=QtEvent)
	decode_failed_event: QtEvent = field(default_factory=QtEvent)

	@property
	def record_id(self):
		return self.decode_record_id

	@property
	def started_event(self):
		return self.decode_started_event

	@property
	def completed_event(self):
		return self.decode_completed_event

	@property
	def file_not_found_event(self):
		return self.decode_file_not_found_event

	@property
	def progress_event(self):
		return self.decode_progress_event

	@property
	def signal_list_event(self):
		return self.decode_signal_list_event

	@property
	def failed_event(self):
		return self.decode_failed_event

	def on_decode_started(self, event: DecodeStartedEvent) -> None:
		self.decode_record_id = event.record_id
		self.decode_started_event.set()

	def on_decode_completed(self, event: DecodeCompletedEvent) -> None:
		self.decode_record_id = event.record_id
		self.decode_completed_event.set()

	def on_decode_file_not_found(self, event: DecodeFileNotFoundEvent) -> None:
		self.decode_file_not_found_event.set()

	def on_decode_progress(self, event: DecodeProgressEvent) -> None:
		self.decode_progress_event.set()

	def on_decode_signal_list(self, event: DecodeSignalListEvent) -> None:
		self.decode_signal_list_event.set()

	def on_decode_status(self, event: DecodeStatusEvent) -> None:
		status = event.status
		if status == DecodeStatus.IDLE:
			self.decode_started_event.set()
		elif status == DecodeStatus.RUNNING:
			self.decode_progress_event.set()
		elif status == DecodeStatus.DONE:
			self.decode_completed_event.set()
		elif status == DecodeStatus.FAILED:
			self.decode_failed_event.set()

	def reset(self) -> None:
		self.decode_record_id = None
		reset_events([
			self.decode_started_event,
			self.decode_completed_event,
			self.decode_file_not_found_event,
			self.decode_progress_event,
			self.decode_signal_list_event,
			self.decode_failed_event,
		])

@dataclass(slots=True)
class FileServiceStatusVM(ServiceStateVM, ParserStatusVM, RecorderStatusVM, DecodeStatusVM):
	def __init__(self):
		ServiceStateVM.__init__(self)
		ParserStatusVM.__init__(self)
		RecorderStatusVM.__init__(self)
		DecodeStatusVM.__init__(self)

	def reset(self):
		ServiceStateVM.reset(self)
		ParserStatusVM.reset(self)
		RecorderStatusVM.reset(self)
		DecodeStatusVM.reset(self)

	@pytest.fixture
	def app_vm() -> FileServiceStatusVM:
		return FileServiceStatusVM()

@pytest.fixture(scope="function")
def file_service(app_vm: FileServiceStatusVM) -> Generator[tuple[FileService, FileServiceStatusVM], None, None]:
	setup_logger(env="DEV", backup_count=30)
	# reuse existing Qt application if pytest-qt (qtbot) already created one
	app = QCoreApplication.instance()
	if app is None:
		app = QCoreApplication([])

	file_srv = get_file_service()
	vm = app_vm
	vm.reset()

	file_srv.start()
	registered_callbacks = [
		(RecorderStatusEvent, vm.on_recorder_status),
		(ParserStatusEvent, vm.on_parser_status),
		(DecodeStatusEvent, vm.on_decode_status),
	]

	# print(f"vm={vm!r}")
	# print(f"type={type(vm)}")
	# print(f"mro={type(vm).mro()}")

	# debug: print ids to verify same VM/Event objects are used by subscribers/tests
	#print(f"subscribed vm id={id(vm)} parser_done_event id={id(vm.parser_done_event)}")

	for evt_type, callback in registered_callbacks:
		file_srv.subscribe(evt_type, callback)

	try:
		yield file_srv, vm
	finally:
		vm.reset()
		# file_srv.unsubscribe_all()
		print("Stop service")
		file_srv.stop()

"""
#BUG
The test creates shared memory with an explicit 8-byte header (shm_size = 8 + ENTRY_SIZE * slots).
The test writer manually updates write_idx in that header with struct.pack_into("<Q", shm.buf, 0, frame_idx + 1)
-> The writer is mocking, not the receiver writer
"""
CAN_SHARED_RING_SHM_NAME = "can_analyzer_ring_v1"
TIMEOUT_STATUS = 0.5
TIMEOUT_STATUS_MS = int(TIMEOUT_STATUS * 1000)
@pytest.fixture(scope="function")
def setup_deload(
	request: pytest.FixtureRequest,
	file_service: tuple[FileService, FileServiceStatusVM],
	qtbot,
	) -> Generator[tuple[FileService, FileServiceStatusVM], None, None]:
	file_srv, vm = file_service

	mock_row_count = int(getattr(request, "param", 2560))

	producer_thread: threading.Thread | None = None
	producer_done = threading.Event()
	producer_stop = threading.Event()

	shm = LogRecordRing(mmap_name=str(CAN_SHARED_RING_SHM_NAME), create=True,)
	shm.open()

	def _build_log_record(frame_idx: int, payload_prefix: str) -> LogRecord:
		record = LogRecord()
		record.timestamp = float(frame_idx) / 1000.0
		record.can_id = frame_idx % 2048
		record.direction = frame_idx % 2
		record.data_len = 64
		# LogRecord.data expects a sequence of integers (SupportsInt/SupportsIndex).
		# Provide a list of byte values instead of raw bytes to satisfy the setter.
		raw = (f"{payload_prefix}-{frame_idx}".encode("ascii") + b"\x00" * 64)[:64]
		record.data = list(raw)
		record.channel = "1"
		return record

	def _mock_ring_writer() -> None:
		for frame_idx in range(mock_row_count):
			if producer_stop.is_set():
				break

			shm.write(
				_build_log_record(
					frame_idx=frame_idx,
					payload_prefix="mock-frame",
				)
			)
			time.sleep(0.002)

		producer_done.set()

	vm.start_track_progress_thread()

	producer_thread = threading.Thread(
		target=_mock_ring_writer,
		daemon=True,
		name="mock-ring-writer",
	)
	producer_thread.start()

	try:
		yield file_srv, vm

		qtbot.waitUntil(
			producer_done.is_set,
			timeout=30_000,
		)

		""" NOTE: Bug assert, the record only collect the frame from the time it starts, if the producer start first 
				then the record frames never reach to mock_row_count
		"""
		# qtbot.waitUntil(
		# 	lambda: (
		# 		vm.record is not None
		# 		and int(vm.record.get_progress_index()) >= mock_row_count
		# 	),
		# 	timeout=30_000,
		# )

		""" Assert metadata"""
		assert vm.record is not None
		assert int(vm.record.get_total_lines()) > 0
		assert isinstance(vm.entries, list)
		assert len(vm.entries) > 0
		assert len(vm.entries) <= 10
		assert all(isinstance(entry, ParsedEntry) for entry in vm.entries)
	
		expected_records = [_build_log_record(i, "mock-frame") for i in range(100, mock_row_count)]
		for expected, actual in zip(expected_records, vm.entries[100:mock_row_count]):
			#assert actual.timestamp == expected.timestamp
			assert actual.can_id == expected.can_id
			assert actual.direction == expected.direction
			assert actual.data_len == expected.data_len
			assert list(actual.data) == list(expected.data)
			assert actual.channel == expected.channel

	finally:
		producer_stop.set()

		if producer_thread is not None:
			producer_thread.join(timeout=2.0)

		vm.stop()
		shm.close(unlink=True)