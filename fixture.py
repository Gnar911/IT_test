from __future__ import annotations

from typing import Generator, TypeAlias

import pytest
import webbrowser
from pathlib import Path
from can_service.srv_if import CANService, get_can_service_facade
from file_service.file_service import get_file_service, FileService
from cs_test.fixture import CanServiceVM
from fs_test.fixture import FileServiceStatusVM
from conftest import TestServices

@pytest.fixture(scope="function")
def all_service(acquire_vcan_devices: tuple[CANService, CanServiceVM], 
				file_service: tuple[FileService, FileServiceStatusVM]) -> Generator[tuple[CANService, FileService, TestServices], None, None]:
	can_srv, vm = acquire_vcan_devices
	file_srv, vm = file_service
	try:
		yield can_srv, file_srv, vm
		""" Un set up fixture continue here !!!"""

		""" Open the debug UI and set the datetime to today by navigating to a small helper
		# HTML that writes the date into localStorage and redirects to the UI."""
		ui_path = Path(__file__).parents[1] / "src" / "network_service" / "debug_webapp" / "open_with_date.html"
		webbrowser.open(ui_path.as_uri())

	finally:
		vm.stop()