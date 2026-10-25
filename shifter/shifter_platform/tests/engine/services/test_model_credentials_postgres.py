"""Concurrent credential rotation against actual PostgreSQL row locks."""

import pytest

from engine.services import authenticate_model_access, exchange_model_enrollment, refresh_model_access
from shared.model_access import ContractError

from .test_model_credentials import _PEER, enrolled_allocation, exchange, issue
from .test_model_request_accounting_postgres import _run_concurrently

pytestmark = [pytest.mark.postgres, pytest.mark.django_db(transaction=True)]
__all__ = ["enrolled_allocation"]


@pytest.mark.parametrize("kind", ["enrollment", "refresh"])
def test_concurrent_one_use_exchange_has_exactly_one_winner(enrolled_allocation, kind):
    enrollment = issue(enrolled_allocation)
    if kind == "enrollment":
        token = enrollment.enrollment_token.get_secret_value()
        operation = exchange_model_enrollment
    else:
        token = exchange(enrollment).refresh_token.get_secret_value()
        operation = refresh_model_access

    def rotate():
        try:
            return operation(token=token, transport_peer=_PEER)
        except ContractError as exc:
            return exc.code

    results = _run_concurrently([rotate, rotate])
    denied = [result for result in results if isinstance(result, str)]
    assert denied == ["credential.unavailable"]
    winner = next(result for result in results if not isinstance(result, str))
    authenticate_model_access(token=winner.access_token.get_secret_value(), transport_peer=_PEER)
