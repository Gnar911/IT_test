import pytest
from can_service.srv_if import CANService, get_can_service_facade
from file_service.srv_if import get_file_service, FileService
from cs_test.fixture import CanServiceVM
from fs_test.fixture import FileServiceStatusVM, ParserStatusEvent, RecorderStatusEvent, DecodeStatusEvent

""" Pytest automatically discovers and loads every conftest.py in your test directory hierarchy. """
pytest_plugins = [
    "cs_test.fixture",
    "fs_test.fixture",
]

class TestServices(CanServiceVM, FileServiceStatusVM):
	"""Combined VM for integration tests that drive both services."""
	def __init__(self) -> None:
		CanServiceVM.__init__(self)
		FileServiceStatusVM.__init__(self)

	def reset(self) -> None:
		CanServiceVM.reset(self)
		FileServiceStatusVM.reset(self)
		
""" Override the vm of acquire_vcan_devices, file_service fixture"""
@pytest.fixture
def app_vm() -> TestServices:
	print("CS app_vm")
	return TestServices()
