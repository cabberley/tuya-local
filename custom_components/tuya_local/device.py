"""
API for Tuya Local devices.
"""

import json
import logging
import tinytuya
from threading import Lock, Timer
from time import time


from homeassistant.const import CONF_HOST, CONF_NAME, UnitOfTemperature
from homeassistant.core import HomeAssistant

from .const import (
    API_PROTOCOL_VERSIONS,
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    DOMAIN,
    CONF_DEVICE_CID,
)
from .helpers.config import get_device_id
from .helpers.device_config import possible_matches


_LOGGER = logging.getLogger(__name__)


class TuyaLocalDevice(object):
    def __init__(self, name, dev_id, address, local_key, cid, hass: HomeAssistant):
        """
        Represents a Tuya-based device.

        Args:
            dev_id (str): The device id.
            address (str): The network address.
            local_key (str): The encryption key.
            cid (str): The sub device id.
        """
        self._name = name
        self._api_protocol_version_index = None
        self._api_protocol_working = False

        parent = None
        tuya_device_id = dev_id
        if cid is not None:
            _LOGGER.info(f"Creating sub device {cid} from gateway {dev_id}.")
            parent = tinytuya.Device(dev_id, address, local_key, persist=True)
            tuya_device_id  = cid
            local_key = None
        self._api = tinytuya.Device(tuya_device_id, address, local_key, cid, parent)
        self.cid = cid
        self._refresh_task = None
        self._rotate_api_protocol_version()

        self._reset_cached_state()

        self._TEMPERATURE_UNIT = UnitOfTemperature.CELSIUS
        self._hass = hass

        # API calls to update Tuya devices are asynchronous and non-blocking.
        # This means you can send a change and immediately request an updated
        # state (like HA does), but because it has not yet finished processing
        # you will be returned the old state.
        # The solution is to keep a temporary list of changed properties that
        # we can overlay onto the state while we wait for the board to update
        # its switches.
        self._FAKE_IT_TIL_YOU_MAKE_IT_TIMEOUT = 10
        self._CACHE_TIMEOUT = 20
        self._CONNECTION_ATTEMPTS = 9
        self._lock = Lock()

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        """Return the unique id for this device (the dev_id or dev_cid)."""
        return self.cid if self.cid is not None else self._api.id

    @property
    def device_info(self):
        """Return the device information for this device."""
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": self.name,
            "manufacturer": "Tuya",
        }

    @property
    def has_returned_state(self):
        """Return True if the device has returned some state."""
        return len(self._get_cached_state()) > 1

    @property
    def temperature_unit(self):
        return self._TEMPERATURE_UNIT

    async def async_possible_types(self):
        cached_state = self._get_cached_state()
        if len(cached_state) <= 1:
            await self.async_refresh()
            cached_state = self._get_cached_state()

        for match in possible_matches(cached_state):
            yield match

    async def async_inferred_type(self):
        best_match = None
        best_quality = 0
        cached_state = {}
        async for config in self.async_possible_types():
            cached_state = self._get_cached_state()
            quality = config.match_quality(cached_state)
            _LOGGER.info(
                f"{self.name} considering {config.name} with quality {quality}"
            )
            if quality > best_quality:
                best_quality = quality
                best_match = config

        if best_match is None:
            _LOGGER.warning(f"Detection for {self.name} with dps {cached_state} failed")
            return None

        return best_match.config_type

    async def async_refresh(self):
        cache = self._get_cached_state()
        if "updated_at" in cache:
            last_updated = self._get_cached_state()["updated_at"]
        else:
            last_updated = 0

        if self._refresh_task is None or time() - last_updated >= self._CACHE_TIMEOUT:
            self._cached_state["updated_at"] = time()
            self._refresh_task = self._hass.async_add_executor_job(self.refresh)

        await self._refresh_task

    def refresh(self):
        _LOGGER.debug(f"Refreshing device state for {self.name}.")
        self._retry_on_failed_connection(
            lambda: self._refresh_cached_state(),
            f"Failed to refresh device state for {self.name}.",
        )

    def get_property(self, dps_id):
        cached_state = self._get_cached_state()
        if dps_id in cached_state:
            return cached_state[dps_id]
        else:
            return None

    def set_property(self, dps_id, value):
        self._set_properties({dps_id: value})

    async def async_set_property(self, dps_id, value):
        await self._hass.async_add_executor_job(self.set_property, dps_id, value)

    async def async_set_properties(self, dps_map):
        await self._hass.async_add_executor_job(self._set_properties, dps_map)

    def anticipate_property_value(self, dps_id, value):
        """
        Update a value in the cached state only. This is good for when you know the device will reflect a new state in
        the next update, but don't want to wait for that update for the device to represent this state.

        The anticipated value will be cleared with the next update.
        """
        self._cached_state[dps_id] = value

    def _reset_cached_state(self):
        self._cached_state = {"updated_at": 0}
        self._pending_updates = {}
        self._last_connection = 0

    def _refresh_cached_state(self):
        new_state = self._api.status()
        self._cached_state = self._cached_state | new_state["dps"]
        self._cached_state["updated_at"] = time()
        _LOGGER.debug(f"{self.name} refreshed device state: {json.dumps(new_state)}")
        _LOGGER.debug(
            f"new cache state (including pending properties): {json.dumps(self._get_cached_state())}"
        )

    def _set_properties(self, properties):
        if len(properties) == 0:
            return

        self._add_properties_to_pending_updates(properties)
        self._debounce_sending_updates()

    def _add_properties_to_pending_updates(self, properties):
        now = time()

        pending_updates = self._get_pending_updates()
        for key, value in properties.items():
            pending_updates[key] = {"value": value, "updated_at": now}

        _LOGGER.debug(
            f"{self.name} new pending updates: {json.dumps(self._pending_updates)}"
        )

    def _debounce_sending_updates(self):
        now = time()
        since = now - self._last_connection
        # set this now to avoid a race condition, it will be updated later
        # when the data is actally sent
        self._last_connection = now
        # Only delay a second if there was recently another command.
        # Otherwise delay 1ms, to keep things simple by reusing the
        # same send mechanism.
        waittime = 1 if since < 1.0 else 0.001

        try:
            self._debounce.cancel()
        except AttributeError:
            pass
        self._debounce = Timer(waittime, self._send_pending_updates)
        self._debounce.start()

    def _send_pending_updates(self):
        pending_properties = self._get_pending_properties()
        payload = self._api.generate_payload(tinytuya.CONTROL, pending_properties)

        _LOGGER.debug(
            f"{self.name} sending dps update: {json.dumps(pending_properties)}"
        )

        self._retry_on_failed_connection(
            lambda: self._send_payload(payload), "Failed to update device state."
        )

    def _send_payload(self, payload):
        try:
            self._lock.acquire()
            self._api._send_receive(payload)
            self._cached_state["updated_at"] = 0
            now = time()
            self._last_connection = now
            pending_updates = self._get_pending_updates()
            for key, value in pending_updates.items():
                pending_updates[key]["updated_at"] = now
        finally:
            self._lock.release()

    def _retry_on_failed_connection(self, func, error_message):
        for i in range(self._CONNECTION_ATTEMPTS):
            try:
                func()
                self._api_protocol_working = True
                break
            except Exception as e:
                _LOGGER.debug(f"Retrying after exception {e}")
                if i + 1 == self._CONNECTION_ATTEMPTS:
                    self._reset_cached_state()
                    self._api_protocol_working = False
                    _LOGGER.error(error_message)
                if not self._api_protocol_working:
                    self._rotate_api_protocol_version()

    def _get_cached_state(self):
        cached_state = self._cached_state.copy()
        return {**cached_state, **self._get_pending_properties()}

    def _get_pending_properties(self):
        return {key: info["value"] for key, info in self._get_pending_updates().items()}

    def _get_pending_updates(self):
        now = time()
        self._pending_updates = {
            key: value
            for key, value in self._pending_updates.items()
            if now - value["updated_at"] < self._FAKE_IT_TIL_YOU_MAKE_IT_TIMEOUT
        }
        return self._pending_updates

    def _rotate_api_protocol_version(self):
        if self._api_protocol_version_index is None:
            self._api_protocol_version_index = 0
        else:
            self._api_protocol_version_index += 1

        if self._api_protocol_version_index >= len(API_PROTOCOL_VERSIONS):
            self._api_protocol_version_index = 0

        new_version = API_PROTOCOL_VERSIONS[self._api_protocol_version_index]
        _LOGGER.info(f"Setting protocol version for {self.name} to {new_version}.")
        self._api.set_version(new_version)

    @staticmethod
    def get_key_for_value(obj, value, fallback=None):
        keys = list(obj.keys())
        values = list(obj.values())
        return keys[values.index(value)] if value in values else fallback


def setup_device(hass: HomeAssistant, config: dict):
    """Setup a tuya device based on passed in config."""

    _LOGGER.info(f"Creating device: {get_device_id(config)}")
    hass.data[DOMAIN] = hass.data.get(DOMAIN, {})
    device = TuyaLocalDevice(
        config[CONF_NAME],
        config[CONF_DEVICE_ID],
        config[CONF_HOST],
        config[CONF_LOCAL_KEY],
        config[CONF_DEVICE_CID] if CONF_DEVICE_CID in config else None,
        hass,
    )
    hass.data[DOMAIN][get_device_id(config)] = {"device": device}

    return device

def delete_device(hass: HomeAssistant, config: dict):
    device_id = get_device_id(config)
    _LOGGER.info(f"Deleting device: {device_id}")
    del hass.data[DOMAIN][device_id]["device"]
