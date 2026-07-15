from __future__ import annotations

import threading
import time
import subprocess
from pathlib import Path
import pytest

from file_service.application_events import (
    DBCLoadedEvent,
)
# from file_service.record_id import RecordId
from file_service.file_service import FileService, get_file_service
from file_service.status import ParserStatus
from fixture import FileServiceStatusVM
from lw.test_event import wait

TIMEOUT_QUERY_MS = 30
TIMEOUT = 0.8
PARSE_TIMEOUT = 15.0
POLL_INTERVAL = 0.1

def _run_segment_discovery(token_path: str) -> None:
    tests_bin = (
        Path(__file__).resolve().parents[2]
        / "file_srv_core"
        / "src"
        / "build"
        / "file_service_core_tests"
    )
    subprocess.check_call(
        [
            str(tests_bin),
            "--gtest_filter=ParsedMmapInterfaceApi.SegmentDiscovery",
            f"--token_path={token_path}",
        ]
    )

@pytest.mark.parametrize(
    "text_line, expected_can_id, expected_channel, expected_data_len, expected_direction, expected_hex_data",
    [
        ("0.000001 1 123 Tx d 8 01 02 03 04 05 06 07 08", 0x123, "1", 8, "Tx", "01 02 03 04 05 06 07 08"),
        ("1.250000 7 1A5 Rx d 4 AA BB CC DD", 0x1A5, "7", 4, "Rx", "AA BB CC DD"),
        ("151.610837 CANFD   1 Tx        4f3  Meter_Infomation                 1 0 8  8 00 00 06 40 00 00 00 45   105500  136   303040 98000288 50500250 46140250 20010f3e 2001050c", 0x4F3, "1", 8, "Tx", "00 00 06 40 00 00 00 45"),
    ],
)
def test_40_parse_line(
    # file_service: FileService,
    text_line: str,
    expected_can_id: int,
    expected_channel: str,
    expected_data_len: int,
    expected_direction: str,
    expected_hex_data: str,
) -> None:
    #assert get_file_service().detect_line_format(text_line)
    parsed =  get_file_service().parse_line(text_line)
    assert parsed
    parsed_hex_data = " ".join(f"{int(parsed.data[i]):02X}" for i in range(int(parsed.data_len)))
    parsed_direction = "Tx" if int(parsed.direction) == 1 else "Rx"

    assert int(parsed.can_id) == expected_can_id
    assert str(parsed.channel) == expected_channel
    assert int(parsed.data_len) == expected_data_len
    assert parsed_direction == expected_direction
    assert parsed_hex_data == expected_hex_data


@pytest.mark.parametrize(
    "text_lines, expected_can_ids, expected_channels, expected_data_lens, expected_directions, expected_hex_data",
    [
        (
            "0.000001 1 123 Tx d 8 01 02 03 04 05 06 07 08\n1.250000 7 1A5 Rx d 4 AA BB CC DD",
            [0x123, 0x1A5],
            ["1", "7"],
            [8, 4],
            ["Tx", "Rx"],
            [
                "01 02 03 04 05 06 07 08",
                "AA BB CC DD",
            ],
        ),
        (
            "152.266280 CANFD   1 Tx        165  EngControlData                   1 0 d 32 00 00 00 00 00 00 00 00 00 00 00 00 00 00 18 00 20 00 00 80 00 00 00 00 00 00 00 00 00 00 00 00   223516  372   303040 c80987db 50500250 46140250 20010f3e 2001050c\n"
            "152.266391 CANFD   1 Tx         74  YAW_Rate_Brake_Control_1_2_MAC   1 0 8  8 04 c6 00 46 3a 81 55 cc   104516  131   323040 f8008e2c 50500250 46140250 20010f3e 2001050c\n"
            "152.266744 CANFD   1 Tx         81  VSC1G12                          1 0 d 32 02 00 02 00 02 00 00 00 0b b8 0b b8 27 10 00 00 00 00 00 00 00 00 00 00 00 00 00 00 f6 fc b9 51   220000  362   303040 e0139bde 50500250 46140250 20010f3e 2001050c\n"
            "152.266973 CANFD   1 Tx        3d9  ADAS_MAP_Information1            1 0 d 32 ff ff ff ff ff ff ff 00 ff ff fc 03 ff c0 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00   223000  371   323040 8001abac 50500250 46140250 20010f3e 2001050c\n"
            "152.268302 CANFD   1 Tx        260  Information4x4                   1 0 d 32 20 00 00 00 80 00 0f a0 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00   225000  372   303040 c80c1d7c 50500250 46140250 20010f3e 2001050c\n"
            "152.268610 CANFD   1 Tx        40c  GCC_Config_Mgmt2                 1 0 8  8 14 ff ff ff ff ff ff ff   108500  139   303040 f8011952 50500250 46140250 20010f3e 2001050c\n"
            "152.268724 CANFD   1 Tx        228  TransGearData                    1 0 8  8 ee 00 01 00 00 e0 00 01   107500  137   323040 d0005632 50500250 46140250 20010f3e 2001050c\n"
            "152.270000    SV: 2 0 1 ::PVM::TchPosIntrvlX = 0\n"
            "152.270000    SV: 2 0 1 ::PVM::TchPosIntrvlY = 0\n"
            "152.270263 CANFD   1 Tx        1f9  ENG1G40                          1 0 d 32 00 00 00 50 08 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00   225500  373   303040 98173bb7 50500250 46140250 20010f3e 2001050c\n"
            "152.270375 CANFD   1 Tx         87  EPAS_SAS_Info_2_MAC              1 0 8  8 00 80 7f fe 00 00 00 00   106000  137   323040 d001d7da 50500250 46140250 20010f3e 2001050c\n"
            "152.270603 CANFD   1 Tx        350  AVN1SA6                          1 0 8  8 00 00 00 00 00 00 00 00   109000  140   323040 a80111a2 50500250 46140250 20010f3e 2001050c\n"
            "152.270712 CANFD   1 Tx        215  WheelSpeed                       1 0 8  8 27 10 27 10 27 10 27 10   102500  130   323040 b0013979 50500250 46140250 20010f3e 2001050c\n"
            "152.270824 CANFD   1 Tx        21c  AVN1S73                          1 0 8  8 00 00 00 00 00 00 00 00   102800  128   323040 12345678 50500250 46140250 20010f3e 2001050c",
            [0x165, 0x74, 0x81, 0x3D9, 0x260, 0x40C, 0x228, 0x1F9, 0x87, 0x350, 0x215, 0x21C],
            ["1"] * 12,
            [32, 8, 32, 32, 32, 8, 8, 32, 8, 8, 8, 8],
            ["Tx"] * 12,
            [
                "00 00 00 00 00 00 00 00 00 00 00 00 00 00 18 00 20 00 00 80 00 00 00 00 00 00 00 00 00 00 00 00",
                "04 C6 00 46 3A 81 55 CC",
                "02 00 02 00 02 00 00 00 0B B8 0B B8 27 10 00 00 00 00 00 00 00 00 00 00 00 00 00 00 F6 FC B9 51",
                "FF FF FF FF FF FF FF 00 FF FF FC 03 FF C0 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00",
                "20 00 00 00 80 00 0F A0 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00",
                "14 FF FF FF FF FF FF FF",
                "EE 00 01 00 00 E0 00 01",
                "00 00 00 50 08 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00",
                "00 80 7F FE 00 00 00 00",
                "00 00 00 00 00 00 00 00",
                "27 10 27 10 27 10 27 10",
                "00 00 00 00 00 00 00 00",
            ],
        ),
    ],
)
def test_41_parse_lines(
    #file_service: FileService,
    text_lines: str,
    expected_can_ids: list[int],
    expected_channels: list[str],
    expected_data_lens: list[int],
    expected_directions: list[str],
    expected_hex_data: list[str],
) -> None:
    parsed_lines = get_file_service().parse_lines(text_lines)
    parsed_channels = [str(item.channel) for item in parsed_lines]
    parsed_directions = ["Tx" if int(item.direction) == 1 else "Rx" for item in parsed_lines]
    parsed_hex_data_values = [
        " ".join(f"{int(item.data[i]):02X}" for i in range(int(item.data_len)))
        for item in parsed_lines
    ]

    assert len(parsed_lines) == len(expected_can_ids)
    assert [int(item.can_id) for item in parsed_lines] == expected_can_ids
    assert parsed_channels == expected_channels
    assert [int(item.data_len) for item in parsed_lines] == expected_data_lens
    assert parsed_directions == expected_directions
    def _norm(s: str) -> list[str]:
        return [tok.upper() for tok in s.split()]

    assert [_norm(s) for s in parsed_hex_data_values] == [_norm(s) for s in expected_hex_data]



@pytest.mark.parametrize(
    "file_path",
    [
        "/home/gnar911/Desktop/2025-02-11_11-14-53_仕様情報切替 1.asc",
    ],
)
def test_05_parse_log(file_service: tuple[FileService, FileServiceStatusVM], file_path: str) -> None:
    _, vm = file_service

    """ NOTE: using the ViewModel function instead"""
    #assert file_srv.parse_log(file_path)
    vm.startParsing(file_path)
    assert vm.parser_done_event.wait(PARSE_TIMEOUT)

    visible_entries = wait(lambda: vm.entries, max_ms=TIMEOUT_QUERY_MS)
    total = wait(lambda: vm.totalLines, max_ms=TIMEOUT_QUERY_MS)
    assert vm.log_id is not None
    log_id = vm.log_id
    # wait(lambda: _.read_all_entries(log_id), max_ms=TIMEOUT_QUERY_MS)
    # for entry in visible_entries:
    #     print(
    #         {
    #             "line_number": int(entry.line_number),
    #             "timestamp": float(entry.timestamp),
    #             "last_timestamp": float(entry.last_timestamp),
    #             "can_id": int(entry.can_id),
    #             "direction": int(entry.direction),
    #             "data_len": int(entry.data_len),
    #             "changed": int(entry.changed),
    #         }
    #     )
    print(total)

@pytest.mark.parametrize(
    "db_file_path",
    [
        "/home/gnar911/Desktop/20260122 APP WEBSITE - CAN ANALYZER 3.0 CBCM TOOL APP ARC/CAN_Analyzer_MVVM/Database/"
        "EEA10_CANFD_R00c_withADAS_Main.dbc",
    ],
)
def test_07_parse_dbc_without_record(file_service: FileService, qt_app, db_file_path: str) -> None:
    callback_event = threading.Event()
    callback_data: DBCLoadedEvent | None = None
    app = qt_app
    file_srv = file_service

    def _on_dbc_loaded(event: DBCLoadedEvent) -> None:
        nonlocal callback_data
        callback_data = event
        if event.db_file_path == db_file_path and event.record_id is not None:
            callback_event.set()

    file_srv.subscribe(DBCLoadedEvent, _on_dbc_loaded)

    parsed = file_srv.parse_dbc(db_file_path)
    assert parsed

    deadline = time.monotonic() + PARSE_TIMEOUT
    while not callback_event.is_set() and time.monotonic() < deadline:
        app.processEvents()
        callback_event.wait(timeout=POLL_INTERVAL)

    assert callback_event.is_set()
    assert callback_data is not None
    assert callback_data.record_id is not None
    assert callback_data.db_file_path == db_file_path
    assert callback_data.candb_info is not None
    assert callback_data.candb_info.file_path == db_file_path
    assert callback_data.candb_info.db is not None

    record = file_srv.get_record(callback_data.record_id)
    assert record is not None
    pkl_path = record.get_dbc_pkl_path()
    print("dbc_pkl_path(no-record):", pkl_path)
    assert pkl_path.exists()

@pytest.mark.parametrize(
    "file_path, db_file_path",
    [
        (
            "/home/gnar911/Desktop/2025-02-11_11-14-53_仕様情報切替 1.asc",
            "/home/gnar911/Desktop/20260122 APP WEBSITE - CAN ANALYZER 3.0 CBCM TOOL APP ARC/CAN_Analyzer_MVVM/Database/"
            "EEA10_CANFD_R00c_withADAS_Main.dbc",
        ),
    ],
)
def test_09_parse_log_then_dbc_same_record(file_service: FileService, qt_app, file_path: str, db_file_path: str) -> None:
    """parse_log (no pre-created record) → use returned record_id → parse_dbc for that record."""
    parse_event = threading.Event()
    dbc_event = threading.Event()
    app = qt_app
    file_srv = file_service

    parsed_record_id: RecordId | None = None
    dbc_callback_data: DBCLoadedEvent | None = None

    def _on_parser_status(event: ParserStatusEvent) -> None:
        nonlocal parsed_record_id
        if event.status == ParserStatus.DONE and event.record_id is not None:
            parsed_record_id = event.record_id
            parse_event.set()

    def _on_dbc_loaded(event: DBCLoadedEvent) -> None:
        nonlocal dbc_callback_data
        if parsed_record_id is not None and event.record_id == parsed_record_id:
            dbc_callback_data = event
            dbc_event.set()

    file_srv.subscribe(ParserStatusEvent, _on_parser_status)
    file_srv.subscribe(DBCLoadedEvent, _on_dbc_loaded)

    # Step 1: parse log without pre-created record — record_id comes from DONE event
    started = file_srv.parse_log(file_path)
    assert started

    parse_deadline = time.monotonic() + PARSE_TIMEOUT
    while not parse_event.is_set() and time.monotonic() < parse_deadline:
        app.processEvents()
        parse_event.wait(timeout=POLL_INTERVAL)

    assert parse_event.is_set()
    assert parsed_record_id is not None

    # Step 2: parse dbc for that same record
    dbc_parsed = file_srv.parse_dbc(db_file_path, parsed_record_id)
    assert dbc_parsed

    dbc_deadline = time.monotonic() + PARSE_TIMEOUT
    while not dbc_event.is_set() and time.monotonic() < dbc_deadline:
        app.processEvents()
        dbc_event.wait(timeout=POLL_INTERVAL)

    assert dbc_event.is_set()
    assert dbc_callback_data is not None
    assert dbc_callback_data.record_id == parsed_record_id
    assert dbc_callback_data.candb_info is not None

    record = file_srv.get_record(parsed_record_id)
    assert record is not None
    pkl_path = record.get_dbc_pkl_path()
    _run_segment_discovery(str(record.get_base_path()))
    print("test_09 record_id:", parsed_record_id)
    print("test_09 dbc_pkl_path:", pkl_path)
    assert pkl_path.exists()


@pytest.mark.parametrize(
    "file_path, db_file_path",
    [
        (
            "/home/gnar911/Desktop/2025-02-11_11-14-53_仕様情報切替 1.asc",
            "/home/gnar911/Desktop/20260122 APP WEBSITE - CAN ANALYZER 3.0 CBCM TOOL APP ARC/CAN_Analyzer_MVVM/Database/"
            "EEA10_CANFD_R00c_withADAS_Main.dbc",
        ),
    ],
)
def test_10_parse_dbc_then_log_same_record(file_service: FileService, qt_app, file_path: str, db_file_path: str) -> None:
    """parse_dbc (no pre-created record) → use returned record_id → parse_log for that record."""
    parse_event = threading.Event()
    dbc_event = threading.Event()
    app = qt_app
    file_srv = file_service

    dbc_record_id: RecordId | None = None
    parsed_record_id: RecordId | None = None

    def _on_dbc_loaded(event: DBCLoadedEvent) -> None:
        nonlocal dbc_record_id
        if event.db_file_path == db_file_path and event.record_id is not None:
            dbc_record_id = event.record_id
            dbc_event.set()

    def _on_parser_status(event: ParserStatusEvent) -> None:
        nonlocal parsed_record_id
        if (
            event.status == ParserStatus.DONE
            and event.record_id is not None
            and event.record_id == dbc_record_id
        ):
            parsed_record_id = event.record_id
            parse_event.set()

    file_srv.subscribe(DBCLoadedEvent, _on_dbc_loaded)
    file_srv.subscribe(ParserStatusEvent, _on_parser_status)

    # Step 1: parse dbc without pre-created record — record_id comes from DBCLoadedEvent
    dbc_parsed = file_srv.parse_dbc(db_file_path)
    assert dbc_parsed

    dbc_deadline = time.monotonic() + PARSE_TIMEOUT
    while not dbc_event.is_set() and time.monotonic() < dbc_deadline:
        app.processEvents()
        dbc_event.wait(timeout=POLL_INTERVAL)

    assert dbc_event.is_set()
    assert dbc_record_id is not None

    # Step 2: parse log with that same record
    started = file_srv.parse_log(file_path, dbc_record_id)
    assert started

    parse_deadline = time.monotonic() + PARSE_TIMEOUT
    while not parse_event.is_set() and time.monotonic() < parse_deadline:
        app.processEvents()
        parse_event.wait(timeout=POLL_INTERVAL)

    assert parse_event.is_set()
    assert parsed_record_id is not None
    assert parsed_record_id == dbc_record_id

    record = file_srv.get_record(dbc_record_id)
    assert record is not None
    pkl_path = record.get_dbc_pkl_path()
    print("test_10 record_id:", dbc_record_id)
    print("test_10 dbc_pkl_path:", pkl_path)
    _run_segment_discovery(str(record.get_base_path()))
    assert pkl_path.exists()

@pytest.mark.parametrize(
    "file_path, db_file_path",
    [
        (
            "/home/gnar911/Desktop/2025-02-11_11-14-53_仕様情報切替 1.asc",
            "/home/gnar911/Desktop/20260122 APP WEBSITE - CAN ANALYZER 3.0 CBCM TOOL APP ARC/CAN_Analyzer_MVVM/Database/"
            "EEA10_CANFD_R00c_withADAS_Main.dbc",
        ),
    ],
)
def test_16_parse_dbc_then_parse_log(file_service: FileService, qt_app, file_path: str, db_file_path: str) -> None:
    dbc_event = threading.Event()
    parse_event = threading.Event()
    app = qt_app
    file_srv = file_service

    dbc_record_id: RecordId | None = None
    parsed_record_id: RecordId | None = None

    def _on_dbc_loaded(event: DBCLoadedEvent) -> None:
        nonlocal dbc_record_id
        if event.db_file_path == db_file_path and event.record_id is not None:
            dbc_record_id = event.record_id
            dbc_event.set()

    def _on_parser_status(event: ParserStatusEvent) -> None:
        nonlocal parsed_record_id
        if (
            event.status == ParserStatus.DONE
            and event.record_id is not None
            and event.record_id == dbc_record_id
        ):
            parsed_record_id = event.record_id
            parse_event.set()

    file_srv.subscribe(DBCLoadedEvent, _on_dbc_loaded)
    file_srv.subscribe(ParserStatusEvent, _on_parser_status)

    dbc_started = file_srv.parse_dbc(db_file_path)
    assert dbc_started

    dbc_deadline = time.monotonic() + PARSE_TIMEOUT
    while not dbc_event.is_set() and time.monotonic() < dbc_deadline:
        app.processEvents()
        dbc_event.wait(timeout=POLL_INTERVAL)

    assert dbc_event.is_set()
    assert dbc_record_id is not None

    parse_started = file_srv.parse_log(file_path, dbc_record_id)
    assert parse_started

    parse_deadline = time.monotonic() + PARSE_TIMEOUT
    while not parse_event.is_set() and time.monotonic() < parse_deadline:
        app.processEvents()
        parse_event.wait(timeout=POLL_INTERVAL)

    assert parse_event.is_set()
    assert parsed_record_id == dbc_record_id

    record = file_srv.get_record(dbc_record_id)
    assert record is not None
    _run_segment_discovery(str(record.get_base_path()))
    print("test_16 record_id:", dbc_record_id)
    print("test_16 dbc_pkl_path:", record.get_dbc_pkl_path())
