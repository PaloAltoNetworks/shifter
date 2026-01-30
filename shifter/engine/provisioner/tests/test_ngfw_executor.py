"""Tests for NGFWExecutor.

Tests pure logic only — no subprocess mocking.
"""

import os
import stat

from executors.ngfw_executor import NGFWExecutor

FAKE_PEM_KEY = """-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACBfRkB0BI5GkNx7JgveB2oUMBJn7wCfHt9gzGJI4MAN6gAAAJA0YH1WNGB9
VgAAAAtzc2gtZWQyNTUxOQAAACBfRkB0BI5GkNx7JgveB2oUMBJn7wCfHt9gzGJI4MAN6g
AAAECezCb96GmXJbEgjTCXlBkKzz0RJZfA5mxoJwjmm7ER6l9GQHQEjkaQ3HsmC94HahQw
EmfvAJ8e32DMYkjgwA3qAAAACGZha2VAa2V5
-----END OPENSSH PRIVATE KEY-----"""


class TestNGFWExecutorInit:
    """Test NGFWExecutor initialization."""

    def test_creates_temp_key_file(self):
        executor = NGFWExecutor(private_key=FAKE_PEM_KEY)
        assert os.path.isfile(executor._key_path)
        executor.close()

    def test_temp_key_file_has_correct_permissions(self):
        executor = NGFWExecutor(private_key=FAKE_PEM_KEY)
        file_stat = os.stat(executor._key_path)
        assert stat.S_IMODE(file_stat.st_mode) == 0o600
        executor.close()

    def test_temp_key_file_contains_key(self):
        executor = NGFWExecutor(private_key=FAKE_PEM_KEY)
        with open(executor._key_path) as f:
            content = f.read()
        assert content == FAKE_PEM_KEY
        executor.close()

    def test_close_removes_temp_key_file(self):
        executor = NGFWExecutor(private_key=FAKE_PEM_KEY)
        key_path = executor._key_path
        executor.close()
        assert not os.path.exists(key_path)

    def test_close_idempotent(self):
        executor = NGFWExecutor(private_key=FAKE_PEM_KEY)
        executor.close()
        executor.close()  # should not raise

    def test_default_username(self):
        executor = NGFWExecutor(private_key=FAKE_PEM_KEY)
        assert executor._username == "admin"
        executor.close()

    def test_custom_username(self):
        executor = NGFWExecutor(private_key=FAKE_PEM_KEY, username="test")
        assert executor._username == "test"
        executor.close()

    def test_default_port(self):
        executor = NGFWExecutor(private_key=FAKE_PEM_KEY)
        assert executor._port == 22
        executor.close()

    def test_custom_port(self):
        executor = NGFWExecutor(private_key=FAKE_PEM_KEY, port=2222)
        assert executor._port == 2222
        executor.close()

    def test_context_manager(self):
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            key_path = executor._key_path
            assert os.path.isfile(key_path)
        assert not os.path.exists(key_path)


class TestBuildSSHArgs:
    """Test SSH argument construction."""

    def test_basic_ssh_args(self):
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            args = executor._build_ssh_args("10.0.0.1")
            assert args[0] == "ssh"
            assert "-i" in args
            assert executor._key_path in args
            assert "-p" in args
            assert "22" in args
            assert "admin@10.0.0.1" in args

    def test_strict_host_key_checking_off(self):
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            args = executor._build_ssh_args("10.0.0.1")
            args_str = " ".join(args)
            assert "StrictHostKeyChecking=no" in args_str

    def test_user_known_hosts_devnull(self):
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            args = executor._build_ssh_args("10.0.0.1")
            args_str = " ".join(args)
            assert "UserKnownHostsFile=/dev/null" in args_str

    def test_connect_timeout(self):
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            args = executor._build_ssh_args("10.0.0.1")
            args_str = " ".join(args)
            assert "ConnectTimeout=10" in args_str

    def test_custom_port_in_args(self):
        with NGFWExecutor(private_key=FAKE_PEM_KEY, port=2222) as executor:
            args = executor._build_ssh_args("10.0.0.1")
            assert "2222" in args

    def test_custom_username_in_args(self):
        with NGFWExecutor(private_key=FAKE_PEM_KEY, username="root") as executor:
            args = executor._build_ssh_args("10.0.0.1")
            assert "root@10.0.0.1" in args


class TestBuildCommandInput:
    """Test command input string construction."""

    def test_script_only(self):
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            result = executor._build_command_input("show system info", None)
            assert result == "show system info\n"

    def test_stdin_input_only(self):
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            result = executor._build_command_input("", "configure\nset ...\ncommit")
            assert result == "configure\nset ...\ncommit\n"

    def test_script_and_stdin_input(self):
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            result = executor._build_command_input("set cli pager off", "show system info")
            assert result == "set cli pager off\nshow system info\n"

    def test_trailing_newline_deduplication(self):
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            result = executor._build_command_input("show system info\n", None)
            # Should end with exactly one newline
            assert result.endswith("\n")
            assert not result.endswith("\n\n")


class TestCheckSystemInfoOutput:
    """Test the system info output validation used by wait_for_agent."""

    def test_valid_system_info(self):
        output = """hostname: PA-VM
ip-address: 10.0.0.1
netmask: 255.255.255.0
"""
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            assert executor._is_system_info_ready(output) is True

    def test_missing_hostname(self):
        output = """ip-address: 10.0.0.1
netmask: 255.255.255.0
"""
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            assert executor._is_system_info_ready(output) is False

    def test_missing_ip(self):
        output = """hostname: PA-VM
netmask: 255.255.255.0
"""
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            assert executor._is_system_info_ready(output) is False

    def test_missing_netmask(self):
        output = """hostname: PA-VM
ip-address: 10.0.0.1
"""
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            assert executor._is_system_info_ready(output) is False

    def test_empty_output(self):
        with NGFWExecutor(private_key=FAKE_PEM_KEY) as executor:
            assert executor._is_system_info_ready("") is False
