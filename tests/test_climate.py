"""Tests for the light entity."""
from pytest_homeassistant_custom_component.common import MockConfigEntry
from unittest.mock import AsyncMock, Mock

from custom_components.tuya_local.const import (
    CONF_DEVICE_ID,
    CONF_TYPE,
    DOMAIN,
)
from custom_components.tuya_local.generic.climate import TuyaLocalClimate
from custom_components.tuya_local.climate import async_setup_entry


async def test_init_entry(hass):
    """Test the initialisation."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TYPE: "heater", CONF_DEVICE_ID: "dummy"},
    )
    # although async, the async_add_entities function passed to
    # async_setup_entry is called truly asynchronously. If we use
    # AsyncMock, it expects us to await the result.
    m_add_entities = Mock()
    m_device = AsyncMock()

    hass.data[DOMAIN] = {}
    hass.data[DOMAIN]["dummy"] = {}
    hass.data[DOMAIN]["dummy"]["device"] = m_device

    await async_setup_entry(hass, entry, m_add_entities)
    assert type(hass.data[DOMAIN]["dummy"]["climate"]) == TuyaLocalClimate
    m_add_entities.assert_called_once()


# After removal of deprecated entities, there are no secondary climate devices to test against.
# async def test_init_entry_as_secondary(hass):
#     """Test initialisation when climate is a secondary entity"""
#     entry = MockConfigEntry(
#         domain=DOMAIN,
#         data={
#             CONF_TYPE: "goldair_dehumidifier",
#             CONF_DEVICE_ID: "dummy",
#         },
#     )
#     # although async, the async_add_entities function passed to
#     # async_setup_entry is called truly asynchronously. If we use
#     # AsyncMock, it expects us to await the result.
#     m_add_entities = Mock()
#     m_device = AsyncMock()

#     hass.data[DOMAIN] = {}
#     hass.data[DOMAIN]["dummy"] = {}
#     hass.data[DOMAIN]["dummy"]["device"] = m_device

#     await async_setup_entry(hass, entry, m_add_entities)
#     assert (
#         type(hass.data[DOMAIN]["dummy"]["climate_dehumidifier_as_climate"])
#         == TuyaLocalClimate
#     )
#     m_add_entities.assert_called_once()


async def test_init_entry_fails_if_device_has_no_climate(hass):
    """Test initialisation when device has no matching entity"""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TYPE: "kogan_switch", CONF_DEVICE_ID: "dummy"},
    )
    # although async, the async_add_entities function passed to
    # async_setup_entry is called truly asynchronously. If we use
    # AsyncMock, it expects us to await the result.
    m_add_entities = Mock()
    m_device = AsyncMock()

    hass.data[DOMAIN] = {}
    hass.data[DOMAIN]["dummy"] = {}
    hass.data[DOMAIN]["dummy"]["device"] = m_device
    try:
        await async_setup_entry(hass, entry, m_add_entities)
        assert False
    except ValueError:
        pass
    m_add_entities.assert_not_called()


async def test_init_entry_fails_if_config_is_missing(hass):
    """Test initialisation when device has no matching entity"""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_TYPE: "non_existing", CONF_DEVICE_ID: "dummy"},
    )
    # although async, the async_add_entities function passed to
    # async_setup_entry is called truly asynchronously. If we use
    # AsyncMock, it expects us to await the result.
    m_add_entities = Mock()
    m_device = AsyncMock()

    hass.data[DOMAIN] = {}
    hass.data[DOMAIN]["dummy"] = {}
    hass.data[DOMAIN]["dummy"]["device"] = m_device
    try:
        await async_setup_entry(hass, entry, m_add_entities)
        assert False
    except ValueError:
        pass
    m_add_entities.assert_not_called()
