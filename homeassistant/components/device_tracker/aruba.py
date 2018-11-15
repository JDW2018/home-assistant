"""
Support for Aruba Access Points.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/device_tracker.aruba/
"""
import logging
import re

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.device_tracker import (
    DOMAIN, PLATFORM_SCHEMA, DeviceScanner)
from homeassistant.const import (
    CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_TYPE)

_LOGGER = logging.getLogger(__name__)

REQUIREMENTS = ['pexpect==4.6.0']

_DEVICES_REGEX = re.compile(
    r'(?P<name>([^\s]+)?)\s+' +
    r'(?P<ip>([0-9]{1,3}[\.]){3}[0-9]{1,3})\s+' +
    r'(?P<mac>([0-9a-f]{2}[:-]){5}([0-9a-f]{2}))\s+')

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_TYPE): cv.string
})


def get_scanner(hass, config):
    """Validate the configuration and return a Aruba scanner."""
    scanner = ArubaDeviceScanner(config[DOMAIN])

    return scanner if scanner.success_init else None


class ArubaDeviceScanner(DeviceScanner):
    """This class queries a Aruba Access Point for connected devices."""

    def __init__(self, config):
        """Initialize the scanner."""
        self.host = config[CONF_HOST]
        self.username = config[CONF_USERNAME]
        self.password = config[CONF_PASSWORD]
        self.type = config[CONF_TYPE]
        self.last_results = {}

        # Test the router is accessible.
        data = self.get_aruba_data()
        self.success_init = data is not None

    def scan_devices(self):
        """Scan for new devices and return a list with found device IDs."""
        self._update_info()
        return [client['mac'] for client in self.last_results]

    def get_device_name(self, device):
        """Return the name of the given device or None if we don't know."""
        if not self.last_results:
            return None
        for client in self.last_results:
            if client['mac'] == device:
                return client['name']
        return None

    def _update_info(self):
        """Ensure the information from the Aruba Access Point is up to date.

        Return boolean if scanning successful.
        """
        if not self.success_init:
            return False

        data = self.get_aruba_data()
        if not data:
            return False

        self.last_results = data.values()
        return True

    def get_extra_attributes(self, device):
        """Return the extra info of the given device."""
        filter_att = next((
            {
                'ip': result['ip'].decode('utf-8'),
                'location_name': result['location_name'].decode('utf-8')
            } for result in self.last_results
            if result['mac'] == device), None)
        return filter_att

    def get_aruba_data(self):
        """Retrieve data from Aruba Access Point and return parsed result."""
        import ipaddress
        import pexpect
        connect = 'ssh {}@{}'
        ssh = pexpect.spawn(connect.format(self.username, self.host))
        query = ssh.expect(['password:', pexpect.TIMEOUT, pexpect.EOF,
                            'continue connecting (yes/no)?',
                            'Host key verification failed.',
                            'Connection refused',
                            'Connection timed out'], timeout=120)
        if query == 1:
            _LOGGER.error("Timeout")
            return
        if query == 2:
            _LOGGER.error("Unexpected response from router")
            return
        if query == 3:
            ssh.sendline('yes')
            ssh.expect('password:')
        elif query == 4:
            _LOGGER.error("Host key changed")
            return
        elif query == 5:
            _LOGGER.error("Connection refused by server")
            return
        elif query == 6:
            _LOGGER.error("Connection timed out")
            return

        devices = {}

        if self.type == 'AP':
            ssh.sendline(self.password)
            ssh.expect('>')
            ssh.sendline('enable')
            ssh.expect('Password:')
            ssh.sendline('enable')
            ssh.expect('#')
            ssh.sendline('show user')
            ssh.sendline(' ')
            ssh.sendline(' ')
            ssh.sendline(' ')
            ssh.sendline(' ')
            ssh.sendline(' ')
            ssh.expect('#')
            devices_result = ssh.before.splitlines()
            ssh.sendline('exit')
            ssh.sendline('exit')

            for device in devices_result:
                try:
                    device_elements = device.split()
                    _LOGGER.debug("split %s", device_elements)
                    ipaddress.ip_address(device_elements[0].decode('utf-8'))
                    devices[device_elements[0]] = {
                        'ip': device_elements[0],
                        'mac': device_elements[1],
                        'name': device_elements[10],
                        'location_name': device_elements[4]
                    }

                except (IndexError, ValueError):
                    _LOGGER.debug("No IP found")

        else:
            ssh.sendline(self.password)
            ssh.expect('#')
            ssh.sendline('show clients')
            ssh.expect('#')
            devices_result = ssh.before.split(b'\r\n')
            ssh.sendline('exit')

            for device in devices_result:
                match = _DEVICES_REGEX.search(device.decode('utf-8'))
                if match:
                    devices[match.group('ip')] = {
                        'ip': match.group('ip'),
                        'mac': match.group('mac').upper(),
                        'name': match.group('name')
                    }

        return devices
