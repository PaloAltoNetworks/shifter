"""Image-managed login identities cannot be claimed by authored local accounts."""

from dataclasses import replace

import pytest

from raes_guest_plan import RaesGuestPlanError, assert_management_login_separate
from raes_plan import RaesPlanAccount
from tests.test_ec2_range_network import topology


def test_custom_management_login_cannot_be_overwritten_by_a_local_account():
    account = RaesPlanAccount(username="imageadmin", target_address="node.host", auth_method="key")
    plan = replace(topology(), accounts=(account,))
    with pytest.raises(RaesGuestPlanError):
        assert_management_login_separate(plan, "node.host", "imageadmin")
    assert_management_login_separate(plan, "node.host", "anotheradmin")
