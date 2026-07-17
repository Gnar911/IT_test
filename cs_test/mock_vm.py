from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Any

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
from lw.logger_setup import LOG


def reset_events(events: list[threading.Event]) -> None:
    for event in events:
        event.clear()


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

    def __post_init__(self) -> None:
        # provide legacy/expected attribute names used in fixtures
        self.started_event = self.replay_started_event
        self.paused_event = self.replay_paused_event
        self.resumed_event = self.replay_resumed_event
        self.stopped_event = self.replay_stopped_event
        self.source_set_event = self.replay_source_set_event
        self.source_unset_event = self.replay_source_unset_event
        self.channel_registered_event = self.replay_channel_mapping_event
        self.loop_set_event = self.replay_loop_set_event
        self.repeat_set_event = self.replay_repeat_set_event
        self.filter_set_event = self.replay_filter_set_event
        self.timescope_set_event = self.replay_timescope_set_event

    def on_replay_status(self, status: ResponseACK | NotificationEvent) -> None:
        if isinstance(status, NotificationEvent):
            if isinstance(status.evt, RplFinished):
                self.rpl_finished_event.set()
                return
            if isinstance(status.evt, RplCycleFinished):
                self.rpl_cycle_finished_event.set()
                return

        if not isinstance(status, ResponseACK):
            return

        LOG.info("on_replay_status event=%s cmd_type=%s", type(status).__name__, status.cmd_type)
        if status.cmd_type == ReplayCmdType.START:
            self.replay_started_event.set()
            return
        if status.cmd_type == ReplayCmdType.RESUME:
            self.replay_resumed_event.set()
            return
        if status.cmd_type == ReplayInterruptCmdType.PAUSE:
            self.replay_paused_event.set()
            return
        if status.cmd_type == ReplayInterruptCmdType.STOP:
            self.stopped_event.set()
            return
        if status.cmd_type == ReplayInterruptCmdType.UNSET_SOURCE:
            self.source_unset_event.set()
            return

        key_cls = status.cmd_type
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

    def on_send_status(self, status: ResponseACK) -> None:
        if not isinstance(status, ResponseACK):
            return
        key_cls = status.cmd_type
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
        reset_events([
            self.snd_clear_event,
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
    # available_device: list[Any] = field(default_factory=list)
    # acquired_devices: list[Any] = field(default_factory=list)

    def on_scan_status(self, payload: ResponseACK | NotificationEvent) -> None:
        if isinstance(payload, NotificationEvent):
            if isinstance(payload.evt, ScanDevicePluggedStatus):
                self.plugged_event.set()
                #payload = payload.evt
                #self.available_device.append(payload.device_info)
                return
            if isinstance(payload.evt, ScanDeviceUnpluggedStatus):
                self.unplugged_event.set()
                #payload = payload.evt
                #self.available_device.append(payload.device_info)
                return

        if isinstance(payload, ResponseACK):
            if payload.cmd_type == ScanChannelAcquiredStatus:
                self.acquired_event.set()
                return
            if payload.cmd_type == ScanChannelReleasedStatus:
                self.released_event.set()
                return

    def reset(self) -> None:
        self.plugged_event.clear()
        self.unplugged_event.clear()
        self.acquired_event.clear()
        self.released_event.clear()

@dataclass
class ReceiverVM:
    opened_event: threading.Event = field(default_factory=threading.Event)
    closed_event: threading.Event = field(default_factory=threading.Event)
    rcv_device_acquired_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)
    rcv_device_unacquired_event: EdgeTriggerEvent = field(default_factory=EdgeTriggerEvent)

    def on_receiver_status(self, status: ResponseACK) -> None:
        if not isinstance(status, ResponseACK):
            return
        key_cls = status.cmd_type
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
        self.opened_event.clear()
        self.closed_event.clear()
        self.rcv_device_acquired_event.clear()
        self.rcv_device_unacquired_event.clear()
