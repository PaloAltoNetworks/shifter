"""Tests for SSHConnection.__init__."""

import logging

import pytest

from engine.ssh import SSHConnection


class TestSSHConnectionInit:
    """Tests for SSHConnection initialization."""

    # -------------------------------------------------------------------------
    # Happy path - initialization succeeds
    # -------------------------------------------------------------------------

    def test_stores_host_parameter(self, valid_connection_params):
        """Connection stores host parameter."""
        conn = SSHConnection(**valid_connection_params)

        assert conn.host == valid_connection_params["host"]

    def test_stores_username_parameter(self, valid_connection_params):
        """Connection stores username parameter."""
        conn = SSHConnection(**valid_connection_params)

        assert conn.username == valid_connection_params["username"]

    def test_stores_private_key_parameter(self, valid_connection_params):
        """Connection stores private_key parameter."""
        conn = SSHConnection(**valid_connection_params)

        assert conn.private_key == valid_connection_params["private_key"]

    def test_uses_default_port_when_not_specified(self, valid_connection_params):
        """Connection uses port 22 by default."""
        conn = SSHConnection(**valid_connection_params)

        assert conn.port == 22

    def test_uses_default_term_type_when_not_specified(self, valid_connection_params):
        """Connection uses xterm-256color by default."""
        conn = SSHConnection(**valid_connection_params)

        assert conn.term_type == "xterm-256color"

    def test_uses_default_term_size_when_not_specified(self, valid_connection_params):
        """Connection uses 80x24 terminal size by default."""
        conn = SSHConnection(**valid_connection_params)

        assert conn.term_size == (80, 24)

    def test_stores_custom_port(self, valid_connection_params):
        """Connection stores custom port when specified."""
        conn = SSHConnection(**valid_connection_params, port=2222)

        assert conn.port == 2222

    def test_stores_custom_term_type(self, valid_connection_params):
        """Connection stores custom terminal type when specified."""
        conn = SSHConnection(**valid_connection_params, term_type="vt100")

        assert conn.term_type == "vt100"

    def test_stores_custom_term_size(self, valid_connection_params):
        """Connection stores custom terminal size when specified."""
        conn = SSHConnection(**valid_connection_params, term_size=(120, 40))

        assert conn.term_size == (120, 40)

    def test_initializes_conn_as_none(self, valid_connection_params):
        """Connection initializes internal connection as None."""
        conn = SSHConnection(**valid_connection_params)

        assert conn._conn is None

    def test_initializes_process_as_none(self, valid_connection_params):
        """Connection initializes internal process as None."""
        conn = SSHConnection(**valid_connection_params)

        assert conn._process is None

    # -------------------------------------------------------------------------
    # Input validation - required parameters
    # -------------------------------------------------------------------------

    def test_requires_host_parameter(self):
        """Connection raises TypeError when host is missing."""
        with pytest.raises(TypeError):
            SSHConnection(
                username="testuser",
                private_key="key",
            )

    def test_requires_username_parameter(self):
        """Connection raises TypeError when username is missing."""
        with pytest.raises(TypeError):
            SSHConnection(
                host="10.0.0.1",
                private_key="key",
            )

    def test_requires_private_key_parameter(self):
        """Connection raises TypeError when private_key is missing."""
        with pytest.raises(TypeError):
            SSHConnection(
                host="10.0.0.1",
                username="testuser",
            )

    # -------------------------------------------------------------------------
    # Boundary conditions
    # -------------------------------------------------------------------------

    def test_accepts_empty_string_host(self):
        """Connection accepts empty string for host (validation happens on connect)."""
        conn = SSHConnection(host="", username="testuser", private_key="key")

        assert conn.host == ""

    def test_accepts_empty_string_username(self):
        """Connection accepts empty string for username (validation happens on connect)."""
        conn = SSHConnection(host="10.0.0.1", username="", private_key="key")

        assert conn.username == ""

    def test_accepts_empty_string_private_key(self):
        """Connection accepts empty string for private_key (validation happens on connect)."""
        conn = SSHConnection(host="10.0.0.1", username="testuser", private_key="")

        assert conn.private_key == ""

    def test_accepts_minimum_valid_port(self):
        """Connection accepts port 1."""
        conn = SSHConnection(host="10.0.0.1", username="testuser", private_key="key", port=1)

        assert conn.port == 1

    def test_accepts_maximum_valid_port(self):
        """Connection accepts port 65535."""
        conn = SSHConnection(host="10.0.0.1", username="testuser", private_key="key", port=65535)

        assert conn.port == 65535

    def test_accepts_ipv4_host(self, valid_connection_params):
        """Connection accepts IPv4 address as host."""
        valid_connection_params["host"] = "192.168.1.100"
        conn = SSHConnection(**valid_connection_params)

        assert conn.host == "192.168.1.100"

    def test_accepts_hostname(self, valid_connection_params):
        """Connection accepts hostname as host."""
        valid_connection_params["host"] = "ssh.example.com"
        conn = SSHConnection(**valid_connection_params)

        assert conn.host == "ssh.example.com"

    def test_accepts_ipv6_host(self, valid_connection_params):
        """Connection accepts IPv6 address as host."""
        valid_connection_params["host"] = "::1"
        conn = SSHConnection(**valid_connection_params)

        assert conn.host == "::1"

    def test_accepts_term_size_with_large_dimensions(self, valid_connection_params):
        """Connection accepts large terminal dimensions."""
        conn = SSHConnection(**valid_connection_params, term_size=(400, 100))

        assert conn.term_size == (400, 100)

    def test_accepts_term_size_with_small_dimensions(self, valid_connection_params):
        """Connection accepts small terminal dimensions."""
        conn = SSHConnection(**valid_connection_params, term_size=(1, 1))

        assert conn.term_size == (1, 1)

    # -------------------------------------------------------------------------
    # Output - returns SSHConnection instance
    # -------------------------------------------------------------------------

    def test_returns_ssh_connection_instance(self, valid_connection_params):
        """Initialization returns an SSHConnection instance."""
        conn = SSHConnection(**valid_connection_params)

        assert isinstance(conn, SSHConnection)

    def test_returns_new_instance_each_time(self, valid_connection_params):
        """Each initialization returns a new instance."""
        conn1 = SSHConnection(**valid_connection_params)
        conn2 = SSHConnection(**valid_connection_params)

        assert conn1 is not conn2

    # -------------------------------------------------------------------------
    # Side effects - no external side effects
    # -------------------------------------------------------------------------

    def test_does_not_connect_on_init(self, valid_connection_params):
        """Initialization does not establish a connection."""
        conn = SSHConnection(**valid_connection_params)

        assert conn._conn is None
        assert conn._process is None
        assert conn.is_connected is False

    # -------------------------------------------------------------------------
    # Logging - no logging expected for initialization
    # -------------------------------------------------------------------------

    def test_does_not_log_on_initialization(self, valid_connection_params, caplog):
        """Initialization does not produce log output."""
        with caplog.at_level(logging.DEBUG, logger="engine.ssh"):
            SSHConnection(**valid_connection_params)

        assert caplog.text == ""

    def test_does_not_log_on_initialization_with_options(self, valid_connection_params_with_options, caplog):
        """Initialization with all options does not produce log output."""
        with caplog.at_level(logging.DEBUG, logger="engine.ssh"):
            SSHConnection(**valid_connection_params_with_options)

        assert caplog.text == ""
