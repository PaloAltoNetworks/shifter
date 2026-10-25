"""An accepted write-capability retirement must not hide its retained reads."""

import pytest

from shared.api.contract import _apply_retirement


def test_retirement_removes_only_exact_absent_method():
    base = {"paths": {"/messages/": {"get": {"operationId": "list"}, "post": {}}}}
    current = {"paths": {"/messages/": {"get": {"operationId": "list"}}}}
    _apply_retirement(base, current, {"operations": [{"path": "/messages/", "method": "post"}]})
    assert base == current


def test_retired_operation_cannot_be_reintroduced():
    with pytest.raises(RuntimeError, match="reintroduced"):
        _apply_retirement(
            {"paths": {}},
            {"paths": {"/messages/": {"post": {}}}},
            {"operations": [{"path": "/messages/", "method": "post"}]},
        )
