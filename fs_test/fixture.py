from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generator

import pytest
import threading
from typing import Generator, Callable
from file_service.application_events import FileServiceStateEvent, \
DecodeStartedEvent, DecodeCompletedEvent, DecodeFileNotFoundEvent, DecodeProgressEvent, DecodeSignalListEvent
from file_service.srv_if import FileService, get_file_service
from lw.logger_setup import setup_logger, LOG
from file_service.status import ParserStatus, RecorderStatus, DecodeStatus
# from file_service.status import DecodeStatus
# from file_service.record_id import RecordId
# from file_service.repository.record import Record
from lw.service.base_service import ServiceState
from PySide6.QtCore import QCoreApplication
import time
from file_service.module.fs_core import LogRecord, ParsedEntry
from file_service.recorder.rcd_ring_reader import LogRecordRing
from canapp.vm.record_viewmodel import RecordViewModel
from canapp.vm.log_viewmodel import LogViewModel
from fs_test.mock_vm import DecodeStatusVM, RecordModel, ServiceStateVM

class FileServiceStatusVM(ServiceStateVM, LogViewModel, RecordModel, DecodeStatusVM):
	def __init__(self):
		ServiceStateVM.__init__(self)
		LogViewModel.__init__(self)
		RecordModel.__init__(self)
		DecodeStatusVM.__init__(self)

	def reset(self):
		ServiceStateVM.reset(self)
		LogViewModel.reset(self)
		RecordModel.reset(self)
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
		(RecorderStatus, vm.on_recorder_status),
		(ParserStatus, vm.on_parser_status),
		(DecodeStatus, vm.on_decode_status),
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
		assert vm.record_id is not None
		# assert int(vm.record.get_total_lines()) > 0
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
			assert list(actual.raw_data) == list(expected.data)
			assert actual.channel == expected.channel

	finally:
		producer_stop.set()

		if producer_thread is not None:
			producer_thread.join(timeout=2.0)

		vm.stop()
		shm.close(unlink=True)