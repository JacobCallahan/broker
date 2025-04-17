"""Module for managing hosts.

This module defines the `Host` class, which represents a host that can be accessed via SSH or Bind.
The `Host` class provides methods for connecting to the host, executing commands, and transferring files.
It additionally exposes a common interface for Broker to manage host creation, checkin, and deletion.
It is recommended to subclass the `Host` class for custom behavior.

Usage:
    To use the `Host` class, create a new `Host` object with the required parameters:

    ```
    from broker.hosts import Host

    host = Host(hostname="example.com", username="user", password="password")
    ```
"""

import functools
import inspect

from logzero import logger

from broker.exceptions import HostError, NotImplementedError
from broker.settings import settings

SETTINGS_VALIDATED = False


class Host:
    """Class representing a host that can be accessed via SSH or Bind.

    This class provides methods for connecting to the host, executing commands, and transferring files.
    It additionally exposes a common interface for Broker to manage host creation, checkin, and deletion.
    It is recommended to subclass the `Host` class for custom behavior.
    """

    default_timeout = 0  # timeout in ms, 0 is infinite

    def __init__(self, **kwargs):
        """Create a Host instance.

        Expected kwargs:
            hostname: (str) - Hostname or IP address of the host, required
            name: (str) - Name of the host
            username: (str) - Username to use for SSH connection
            password: (str) - Password to use for SSH connection
            connection_timeout: (int) - Timeout for SSH connection
            port: (int) - Port to use for SSH connection
            key_filename: (str) - Path to SSH key file to use for SSH connection
            ipv6 (bool): Whether or not to use IPv6. Defaults to False.
            ipv4_fallback (bool): Whether or not to fallback to IPv4 if IPv6 fails. Defaults to True.
        """
        global SETTINGS_VALIDATED  # noqa: PLW0603
        if not SETTINGS_VALIDATED:
            logger.debug("Validating ssh settings")
            settings.validators.validate(only="SSH")
            SETTINGS_VALIDATED = True
        logger.debug(f"Constructing host using {kwargs=}")
        self.hostname = kwargs.get("hostname") or kwargs.get("ip")
        if not self.hostname:
            # check to see if we're being reconstructued, likely for checkin
            import inspect

            if any(f.function == "reconstruct_host" for f in inspect.stack()):
                logger.debug("Ignoring missing hostname and ip for checkin reconstruction.")
            else:
                raise HostError("Host must be constructed with a hostname or ip")
        self.name = kwargs.pop("name", None)
        self.username = kwargs.pop("username", settings.SSH.HOST_USERNAME)
        self.password = kwargs.pop("password", settings.SSH.HOST_PASSWORD)
        self.timeout = kwargs.pop("connection_timeout", settings.SSH.HOST_CONNECTION_TIMEOUT)
        self.port = kwargs.pop("port", settings.SSH.HOST_SSH_PORT)
        self.key_filename = kwargs.pop("key_filename", settings.SSH.HOST_SSH_KEY_FILENAME)
        self.ipv6 = kwargs.pop("ipv6", settings.SSH.HOST_IPV6)
        self.ipv4_fallback = kwargs.pop("ipv4_fallback", settings.SSH.HOST_IPV4_FALLBACK)
        self.__dict__.update(kwargs)  # Make every other kwarg an attribute
        self._session = None

    def __del__(self):
        """Try to close the connection on garbage collection of the host instance."""
        if hasattr(self, "_session") and self._session is not None:
            self.close()
        # If host inherits from a different class with __del__, it should get called through super

    @property
    def session(self):
        """Return the session object for the host.

        If the session object does not exist, it will be created by calling the `connect` method.
        If the host is a non-SSH-enabled container host, a `ContainerSession` object will be created instead.
        """
        if self._session is None:
            # Check to see if we're a non-ssh-enabled Container Host
            if hasattr(self, "_cont_inst") and not self._cont_inst.ports.get(22):
                from broker.session import ContainerSession

                runtime = "podman" if "podman" in str(self._cont_inst.client) else "docker"
                self._session = ContainerSession(self, runtime=runtime)
            else:
                self.connect()
        return self._session

    def connect(self, **kwargs):
        """Create one or more connections to the target host."""
        for key, val in kwargs.items():
            setattr(self, key, val)
        if getattr(self, "is_container", None) or getattr(self, "_cont_inst", None):
            from broker.session import ContainerSession

            self.session = ContainerSession(
                self, kwargs.get("runtime"), settings_obj=self._settings
            )
        else:
            logger.debug(f"Creating SSH session to {self.hostname}")
            # Create a session using the entry-points based approach
            from broker.session import make_session

            self.session = make_session(
                settings_obj=self._settings,
                hostname=self.hostname,
                port=getattr(self, "port", self._settings.get("SSH", {}).get("HOST_SSH_PORT", 22)),
                username=getattr(
                    self,
                    "user",
                    self._settings.get("SSH", {}).get("HOST_USERNAME", self.DEFAULT_USER),
                ),
                password=getattr(
                    self,
                    "password",
                    self._settings.get("SSH", {}).get("HOST_PASSWORD", None),
                ),
                key_filename=getattr(
                    self,
                    "key_filename",
                    self._settings.get("SSH", {}).get("HOST_SSH_KEY_FILENAME", None),
                ),
                timeout=getattr(
                    self,
                    "timeout",
                    self._settings.get("SSH", {}).get("HOST_CONNECTION_TIMEOUT", 60),
                ),
                host=self.hostname,  # For hussh backend compatibility
            )

    def close(self):
        """Close the SSH connection to the host."""
        if self._session is not None:
            self._session.disconnect()
        self._session = None

    def release(self):
        """Release the host using the appropriate method for the provider."""
        raise NotImplementedError("release has not been implemented for this provider")

    # @cached_property
    def _pkg_mgr(self):
        for mgr in ["yum", "dnf", "zypper"]:
            if f"no {mgr} in" in self.execute(f"which {mgr}"):
                return mgr
        return None

    def execute(self, command, timeout=None):
        """Execute a command on the host using SSH.

        Args:
            command (str): The command to execute on the host.
            timeout (int): The timeout for the SSH connection in seconds. Defaults to `None`.

        Returns:
            str: The output of the command executed on the host.
        """
        timeout = self.default_timeout if timeout is None else timeout
        logger.debug(f"{self.hostname} executing command: {command}")
        res = self.session.run(command, timeout=timeout)
        logger.debug(f"{self.hostname} command result:\n{res}")
        return res

    def to_dict(self):
        """Return a dict representation of the host."""
        keep_keys = (
            "hostname",
            "_broker_provider",
            "_broker_args",
            "tower_inventory",
            "deploy_network_type",
            "job_id",
            "_attrs",
            "ip",
            "os_distribution",
            "os_distribution_version",
            "reported_devices",
            "exposed_ports",
        )
        ret_dict = {
            "name": getattr(self, "name", None),
            "_broker_provider_instance": self._prov_inst.instance,
            "type": "host",
        }
        ret_dict.update({k: v for k, v in self.__dict__.items() if k in keep_keys})
        return ret_dict

    def setup(self):
        """Automatically ran when entering a Broker context manager."""
        pass

    def teardown(self):
        """Automatically ran when exiting a Broker context manager."""
        pass

    def __repr__(self):
        """Return a string representation of the host."""
        inner = ", ".join(
            f"{k}={v}"
            for k, v in self.__dict__.items()
            if not k.startswith("_") and not callable(v)
        )
        return f"{self.__class__.__name__}({inner})"

    @classmethod
    def from_dict(cls, arg_dict):
        """Create a Host instance from a dict."""
        return cls(**arg_dict, from_dict=True)
