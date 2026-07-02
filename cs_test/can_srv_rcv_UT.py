from __future__ import annotations

import pytest
from can_service.srv_if import CANService
from fixture import CanServiceVM

pytest_plugins = ["fixture"]

TIMEOUT_STATUS = 0.5


def test_open_gateway_route_return_and_status_event(acquire_vcan_devices: tuple[CANService, CanServiceVM]):
	can_srv, vm = acquire_vcan_devices
	if not vm.acquired_devices:
		pytest.skip("No acquired channels available for gateway route test")

	src_info = vm.acquired_devices[0]
	dst_info = vm.acquired_devices[0]

	ret = can_srv.open_gateway_route(
		src_device_info=src_info,
		dst_device_info=dst_info,
		src_can_id=0x123,
		dst_can_id=0x456,
	)
	assert ret is True

	assert vm.opened_event.wait(timeout=TIMEOUT_STATUS)


# def test_close_gateway_routes_status_event(acquire_vcan_devices: tuple[CANService, CanServiceVM]):
# 	can_srv, vm = acquire_vcan_devices

# 	ret = can_srv.close_gateway_routes()
# 	assert ret is None

# 	assert vm.closed_event.wait(timeout=TIMEOUT_STATUS)
			

