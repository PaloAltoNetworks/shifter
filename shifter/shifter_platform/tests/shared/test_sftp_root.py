"""Shape validation for the non-secret Guacamole SFTP root (#375).

``sftp_root_directory`` is untrusted per-image configuration until these checks
run. It is validated at the image-config parser and the closed RAES result
boundary through this one Django-free helper, so both boundaries reject the same
dangerous forms and neither invents a guessed guest directory.
"""

from __future__ import annotations

import pytest

from shared.sftp_root import SftpRootError, normalize_sftp_root_directory


class TestNormalizeSftpRootDirectory:
    @pytest.mark.parametrize(
        "value",
        ["/home/kali", "/home/ubuntu", "/C:/Users/Administrator/Downloads"],
    )
    def test_accepts_known_roots(self, value):
        assert normalize_sftp_root_directory(value) == value

    def test_strips_surrounding_whitespace(self):
        assert normalize_sftp_root_directory("  /home/kali  ") == "/home/kali"

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "   ",
            "home/kali",  # not absolute (Guacamole form is absolute)
            "/home/../etc/shadow",  # traversal
            "/home/..",  # traversal segment
            "C:\\Users\\Administrator",  # backslash is ambiguous; Windows uses /C:/...
            "/home/\x00kali",  # NUL
            "/home/\tkali",  # control char
            "/home/\nkali",  # newline
        ],
    )
    def test_rejects_dangerous_or_malformed(self, value):
        with pytest.raises(SftpRootError):
            normalize_sftp_root_directory(value)

    def test_rejects_non_string(self):
        with pytest.raises(SftpRootError):
            normalize_sftp_root_directory(None)  # type: ignore[arg-type]

    def test_rejects_overlong(self):
        with pytest.raises(SftpRootError):
            normalize_sftp_root_directory("/" + "a" * 4096)
