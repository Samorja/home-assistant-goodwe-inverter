"""Tests for EMS mode handling on inverters reporting unknown EMS codes (GoodWe ESA)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from goodwe import InverterError, OperationMode
import pytest

from custom_components.goodwe import number as gw_number, select as gw_select


def _inverter(ems_mode=0, rated_power=125, read_error=None):
    inverter = MagicMock()
    inverter.serial_number = "5125KCI0257L0063"
    inverter.rated_power = rated_power
    inverter.get_operation_modes = AsyncMock(return_value=(OperationMode.GENERAL,))
    inverter.get_operation_mode = AsyncMock(side_effect=ValueError("unsupported"))
    inverter.get_grid_export_limit = AsyncMock(side_effect=ValueError("unsupported"))
    inverter.get_ongrid_battery_dod = AsyncMock(side_effect=ValueError("unsupported"))
    inverter.settings = MagicMock(return_value=())

    async def read_setting(name):
        if name == "ems_mode":
            if read_error:
                raise read_error
            return ems_mode
        if name == "ems_power_limit":
            return 0
        raise ValueError(name)

    inverter.read_setting = AsyncMock(side_effect=read_setting)
    inverter.write_setting = AsyncMock()
    return inverter


def _entry(inverter):
    return SimpleNamespace(
        runtime_data=SimpleNamespace(inverter=inverter, device_info={})
    )


async def _setup_select(inverter):
    added = []
    await gw_select.async_setup_entry(None, _entry(inverter), added.extend)
    return [e for e in added if isinstance(e, gw_select.InverterEMSModeEntity)]


async def test_unknown_ems_code_creates_entity() -> None:
    """ESA reports EMS mode 0, the entity must still be created."""
    entities = await _setup_select(_inverter(ems_mode=0))
    assert len(entities) == 1
    assert entities[0].current_option is None
    assert "stop" in entities[0].options
    assert len(entities[0].options) == 13


@pytest.mark.parametrize(
    ("code", "option"),
    [(1, "auto"), (10, "sell_power"), (12, "discharge_battery"), (255, "stop")],
)
async def test_known_ems_codes(code, option) -> None:
    """Known register values map to options."""
    entities = await _setup_select(_inverter(ems_mode=code))
    assert entities[0].current_option == option


async def test_ems_not_supported() -> None:
    """No entity when the inverter rejects the EMS register."""
    inverter = _inverter(read_error=InverterError("not supported"))
    assert await _setup_select(inverter) == []


async def test_select_and_update() -> None:
    """Selecting writes the raw code; update reads it back."""
    inverter = _inverter(ems_mode=0)
    entity = (await _setup_select(inverter))[0]
    entity.async_write_ha_state = MagicMock()

    await entity.async_select_option("stop")
    inverter.write_setting.assert_awaited_once_with("ems_mode", 255)
    assert entity.current_option == "stop"

    await entity.async_select_option("charge_battery")
    inverter.write_setting.assert_awaited_with("ems_mode", 11)

    inverter.read_setting.side_effect = None
    inverter.read_setting.return_value = 0
    await entity.async_update()
    assert entity.current_option is None


@pytest.mark.parametrize(
    ("rated", "expected"), [(125, 12500), (29900, 29900), (0, 0), (None, 0)]
)
def test_rated_power_w(rated, expected) -> None:
    """Rated power reported in 100 W units is converted to W."""
    assert gw_number._rated_power_w(SimpleNamespace(rated_power=rated)) == expected


async def test_ems_power_limit_max() -> None:
    """EMS power limit max uses rated power in W."""
    added = []
    await gw_number.async_setup_entry(None, _entry(_inverter()), added.extend)
    limit = next(e for e in added if e.entity_description.key == "ems_power_limit")
    assert limit.native_max_value == 25000
