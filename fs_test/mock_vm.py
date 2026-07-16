from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generator

import pytest
import threading
from typing import Generator, Callable
from file_service.application_events import FileServiceStateEvent, \
DBCLoadedEvent, \
DecodeStartedEvent, DecodeCompletedEvent, DecodeFileNotFoundEvent, DecodeProgressEvent, DecodeSignalListEvent, \
ParserStatusEvent, DecodeStatusEvent, RecorderStatusEvent
from file_service.file_service import FileService, get_file_service
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
from typing_extensions import deprecated
# from canapp.vm.record_viewmodel import RecordViewModel
# from canapp.vm.log_viewmodel import LogViewModel
from lw.test_event import QtEvent


def reset_events(events: list[threading.Event]) -> None:
	"""Reset a list of threading events after each test case."""
	for event in events:
		event.clear()

@dataclass
class RecordModel:
	#record_id: RecordId | None = None
	#record: Record | None = None

	""" NOTE: This is the data to be view on the GUI, so there is no point to store all the database on the RAM, only cache the pages"""
	#page_entries: list[ParsedEntry] = field(default_factory=list)
	#persisted_frames = 0
	recorder_stopped_event: QtEvent = field(default_factory=QtEvent)
	recorder_write_batch_event: QtEvent = field(default_factory=QtEvent)
	recorder_paused_event: QtEvent = field(default_factory=QtEvent)
	recorder_wait_ring_event: QtEvent = field(default_factory=QtEvent)
	# recorder_active_event: QtEvent = field(default_factory=QtEvent)
	progress_stop:  QtEvent = field(default_factory=QtEvent)
	#: QtEvent = field(default_factory=QtEvent)

	""" This is ModelView"""
	def on_recorder_status(self, event: RecorderStatusEvent) -> None:
		status = RecorderStatus(int(event.status))
		if status == RecorderStatus.STOPPED:
			self.recorder_stopped_event.set()
		elif status == RecorderStatus.WRITE_BATCH:
			self.recorder_write_batch_event.set()
		elif status == RecorderStatus.PAUSED:
			self.recorder_paused_event.set()
		elif status == RecorderStatus.WAIT_RING:
			self.recorder_wait_ring_event.set()

	""" This is ModelView"""
	@deprecated("Use QTimer instead for polling thread")
	def on_track_progress(self) -> None: 
		while not self.progress_stop.is_set(): 
			# if self.record is not None: 
			# 	self.persisted_frames = int(self.totalFrames)	
			# 	LOG.info(self.persisted_frames) 	
				time.sleep(0.1)

	@deprecated("Use QTimer instead for polling thread")
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
		#self.record = None
		self.recorder_stopped_event.clear()
		self.recorder_write_batch_event.clear()
		self.recorder_paused_event.clear()
		self.recorder_wait_ring_event.clear()

	""" This is ViewModel"""
	@deprecated("Use service to call this directly on View instead")
	def fetch_page(self, count = 100):
		# if self.record is None:
		# 	return [] 
		# self.entries = self.record.get_page_from_row_indices(0, count)
		#return self.entries
		pass

@dataclass
class DBCModel:
	"""Simple test DBC model for unit tests: records last loaded info and signals when loaded."""
	dbc_loaded_event: QtEvent = field(default_factory=QtEvent)

	def on_dbc_model_loaded(self, event: DBCLoadedEvent) -> None:
		self.dbc_loaded_event.set()

	def reset(self) -> None:
		self.dbc_loaded_event.clear()

@dataclass
class ServiceStateVM:
	#file_state_trace: list[ServiceState] = field(default_factory=list)
	file_running_event: QtEvent = field(default_factory=QtEvent)
	file_stopped_event: QtEvent = field(default_factory=QtEvent)

	def on_file_service_state(self, event: FileServiceStateEvent) -> None:
		state = event.state
		if not isinstance(state, ServiceState):
			raise TypeError(f"FileServiceStateEvent.state must be ServiceState, got {type(state).__name__}")
		#self.file_state_trace.append(state)
		if state == ServiceState.RUNNING:
			self.file_running_event.set()
		elif state == ServiceState.STOPPED:
			self.file_stopped_event.set()

	def reset(self) -> None:
		#self.file_state_trace.clear()
		reset_events([
			self.file_running_event,
			self.file_stopped_event,
		])

@dataclass
class ParseModel:
	parser_idle_event: QtEvent = field(default_factory=QtEvent)
	parser_done_event: QtEvent = field(default_factory=QtEvent)
	parser_failed_event: QtEvent = field(default_factory=QtEvent)

	def __post_init__(self) -> None:
		self.parser_idle_event.set()

	def on_parser_status(self, event: ParserStatusEvent) -> None:
		LOG.info(
			"parser_status_event status=%s", event
		)
		status = ParserStatus(int(event.status))

		if status == ParserStatus.DONE:
			self.parser_done_event.set()
		elif status == ParserStatus.FAILED:
			self.parser_failed_event.set()

	def reset(self) -> None:
		#self.parser_record_id = None
		reset_events([
			self.parser_idle_event,
			#self.parser_running_event,
			self.parser_done_event,
			self.parser_failed_event,
		])
		self.parser_idle_event.set()

@dataclass
class DecodeStatusVM:
	#decode_record_id: RecordId | None = None
	decode_started_event: QtEvent = field(default_factory=QtEvent)
	decode_completed_event: QtEvent = field(default_factory=QtEvent)
	decode_file_not_found_event: QtEvent = field(default_factory=QtEvent)
	decode_progress_event: QtEvent = field(default_factory=QtEvent)
	decode_signal_list_event: QtEvent = field(default_factory=QtEvent)
	decode_failed_event: QtEvent = field(default_factory=QtEvent)

	def on_decode_status(self, event: DecodeStatusEvent) -> None:
		status = DecodeStatus(int(event.status))
		if status == DecodeStatus.DONE:
			self.decode_completed_event.set()
		elif status == DecodeStatus.FAILED:
			self.decode_failed_event.set()

	def reset(self) -> None:
		#self.decode_record_id = None
		reset_events([
			self.decode_started_event,
			self.decode_completed_event,
			self.decode_file_not_found_event,
			self.decode_progress_event,
			self.decode_signal_list_event,
			self.decode_failed_event,
		])
