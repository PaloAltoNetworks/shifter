"""Range-owned EC2 management and participant credentials in Secrets Manager.

No guest receives a provider identity. Credentials converge under deterministic,
opaque names and the provisioner supplies them over the pinned management channel.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError

from utils.crypto import derive_ssh_public_key, generate_rdp_password, generate_ssh_host_keypair, generate_ssh_keypair

if TYPE_CHECKING:
    from raes_account_credentials import RaesAccountCredentialOps
    from raes_active_directory import RaesDirectorySecretOps

_KINDS = frozenset(
    {
        "host-ssh",
        "host-identity",
        "account-password",
        "account-key",
        "domain-dsrm",
        "domain-authority",
        "domain-account",
    }
)
_LENGTHS = {"weak": 12, "medium": 18, "strong": 24}

logger = logging.getLogger(__name__)
# Secrets Manager is eventually consistent: a DescribeSecret/GetSecretValue issued
# immediately after a successful CreateSecret can return ResourceNotFoundException.
# A just-created secret is read back within this bounded window (~11.5s) before the
# absence is treated as real.
_READBACK_ATTEMPTS = 8
_READBACK_INITIAL_DELAY_SECONDS = 0.5
_READBACK_MAX_DELAY_SECONDS = 2.0


class Ec2SecretError(RuntimeError):
    """Value-free credential error safe to report through the lifecycle boundary."""


def _until_visible[T](read: Callable[[], T]) -> T:
    """Read a just-created secret, tolerating Secrets Manager's read-after-write lag.

    Only ResourceNotFoundException is retried, and only within the bounded window;
    every other error (and a secret still absent after the window) propagates.
    """
    delay = _READBACK_INITIAL_DELAY_SECONDS
    for _ in range(_READBACK_ATTEMPTS - 1):
        try:
            return read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                raise
        time.sleep(delay)
        delay = min(delay * 2, _READBACK_MAX_DELAY_SECONDS)
    return read()


class Ec2GuestSecrets:
    """Exact ownership checks, atomic first creation, no implicit rotation."""

    def __init__(self, client: BaseClient, *, environment: str, kms_key: str) -> None:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", environment):
            raise Ec2SecretError("EC2 credential deployment namespace is invalid")
        if not re.fullmatch(
            r"arn:aws(?:-us-gov|-cn)?:kms:[a-z0-9-]+:\d{12}:key/[A-Za-z0-9-]+", kms_key, flags=re.ASCII
        ):
            raise Ec2SecretError("EC2 credentials require an exact deployment KMS key")
        self.client = client
        self.environment = environment
        self.kms_key = kms_key

    def name(self, range_id: int, kind: str, *subjects: str) -> str:
        """Use unambiguous subject encoding; names never reveal authored identities."""
        if type(range_id) is not int or range_id <= 0 or kind not in _KINDS:
            raise Ec2SecretError("EC2 credential scope is invalid")
        if not subjects or any(not isinstance(part, str) or not 1 <= len(part) <= 2048 for part in subjects):
            raise Ec2SecretError("EC2 credential subject is invalid")
        digest = hashlib.sha256(json.dumps(subjects, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()
        return f"shifter/{self.environment}/range/{range_id}/raes/{kind}/{digest}"

    @staticmethod
    def _tags(range_id: int) -> dict[str, str]:
        return {"shifter:system": "shifter", "shifter:range_id": str(range_id), "shifter:credential": "raes"}

    def _owned(self, name: str, range_id: int) -> str:
        row = self.client.describe_secret(SecretId=name)
        tags = {item["Key"]: item["Value"] for item in row.get("Tags", [])}
        arn = row.get("ARN")
        if (
            row.get("Name") != name
            or row.get("DeletedDate")
            or row.get("KmsKeyId") != self.kms_key
            or any(tags.get(key) != value for key, value in self._tags(range_id).items())
            or not isinstance(arn, str)
            or not re.fullmatch(
                r"arn:aws(?:-us-gov|-cn)?:secretsmanager:[a-z0-9-]+:\d{12}:secret:"
                + re.escape(name)
                + r"-[A-Za-z0-9]{6}",
                arn,
                flags=re.ASCII,
            )
        ):
            raise Ec2SecretError("EC2 credential ownership is unavailable")
        return arn

    def ensure(
        self, range_id: int, kind: str, subjects: tuple[str, ...], factory: Callable[[], str], *, create: bool = True
    ) -> tuple[str, str]:
        """Return the committed winner, including when concurrent creation wins."""
        name = self.name(range_id, kind, *subjects)
        try:
            try:
                arn = self._owned(name, range_id)
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
                    raise
                if not create:
                    raise Ec2SecretError("Existing EC2 guest management identity is unavailable") from None
                self._create(name, range_id, factory)
                created = True
                arn = _until_visible(lambda: self._owned(name, range_id))
            else:
                created = False
            value = _until_visible(lambda: self._current_value(arn)) if created else self._current_value(arn)
            if not isinstance(value, str) or not 1 <= len(value.encode()) <= 65536:
                raise Ec2SecretError("EC2 credential payload is unavailable")
            return arn, value
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            # The provider error code is value-free (never the response message).
            logger.warning("EC2 credential operation failed range_id=%s kind=%s code=%s", range_id, kind, code)
            raise Ec2SecretError(f"EC2 credential operation failed ({code})") from None
        except BotoCoreError as exc:
            logger.warning(
                "EC2 credential operation failed range_id=%s kind=%s error_type=%s", range_id, kind, type(exc).__name__
            )
            raise Ec2SecretError(f"EC2 credential operation failed ({type(exc).__name__})") from None

    def _current_value(self, arn: str) -> object:
        """Return the AWSCURRENT payload of an owned secret (validated by the caller)."""
        return self.client.get_secret_value(SecretId=arn, VersionStage="AWSCURRENT").get("SecretString")

    def _create(self, name: str, range_id: int, factory: Callable[[], str]) -> None:
        """Atomically create bounded credential bytes, accepting a concurrent winner."""
        value = factory()
        if not isinstance(value, str) or not 1 <= len(value.encode()) <= 65536:
            raise Ec2SecretError("EC2 credential payload is invalid") from None
        try:
            self.client.create_secret(
                Name=name,
                SecretString=value,
                KmsKeyId=self.kms_key,
                Tags=[{"Key": key, "Value": value} for key, value in self._tags(range_id).items()],
            )
        except ClientError as collision:
            if collision.response.get("Error", {}).get("Code") != "ResourceExistsException":
                raise

    def delete(self, range_id: int, kind: str, subjects: tuple[str, ...]) -> None:
        """Delete only a proven range-owned credential; absence is idempotent."""
        name = self.name(range_id, kind, *subjects)
        try:
            arn = self._owned(name, range_id)
            self.client.delete_secret(SecretId=arn, ForceDeleteWithoutRecovery=True)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "ResourceNotFoundException":
                raise Ec2SecretError(f"EC2 credential deletion failed ({code})") from None
        except BotoCoreError as exc:
            raise Ec2SecretError(f"EC2 credential deletion failed ({type(exc).__name__})") from None

    def host_ssh(self, range_id: int, instance_key: str, *, create: bool = True) -> tuple[str, str]:
        ref, value = self.ensure(
            range_id, "host-ssh", (instance_key,), lambda: generate_ssh_keypair()[0], create=create
        )
        return ref, derive_ssh_public_key(value)

    def host_identity(self, range_id: int, instance_key: str, *, create: bool = True) -> tuple[str, str]:
        """Persist the issued host key across create retries; it never leaves provisioning."""
        _, value = self.ensure(
            range_id, "host-identity", (instance_key,), lambda: json.dumps(generate_ssh_host_keypair()), create=create
        )
        keys = json.loads(value)
        if not isinstance(keys, list) or len(keys) != 2 or not all(isinstance(key, str) and key for key in keys):
            raise Ec2SecretError("EC2 host identity is invalid")
        return keys[0], keys[1]

    def _password(self, range_id: int, kind: str, subjects: tuple[str, ...], strength: str) -> tuple[str, str]:
        if strength not in _LENGTHS:
            raise Ec2SecretError("EC2 credential strength is invalid")
        return self.ensure(range_id, kind, subjects, lambda: generate_rdp_password(_LENGTHS[strength]))

    def account_password(self, range_id: int, instance_key: str, username: str, strength: str) -> tuple[str, str]:
        return self._password(range_id, "account-password", (instance_key, username), strength)

    def account_key(self, range_id: int, instance_key: str, username: str) -> tuple[str, str]:
        ref, value = self.ensure(range_id, "account-key", (instance_key, username), lambda: generate_ssh_keypair()[0])
        return ref, derive_ssh_public_key(value)

    def delete_account(self, range_id: int, instance_key: str, username: str, auth_method: str) -> None:
        if auth_method not in {"password", "key"}:
            raise Ec2SecretError("EC2 account authentication method is invalid")
        self.delete(range_id, f"account-{auth_method}", (instance_key, username))

    def domain_dsrm(self, range_id: int, domain_id: str) -> tuple[str, str]:
        return self._password(range_id, "domain-dsrm", (domain_id,), "strong")

    def domain_authority(self, range_id: int, domain_id: str, strength: str) -> tuple[str, str]:
        return self._password(range_id, "domain-authority", (domain_id,), strength)

    def domain_account(self, range_id: int, domain_id: str, account: str, strength: str) -> tuple[str, str]:
        return self._password(range_id, "domain-account", (domain_id, account), strength)

    def account_ops(self) -> RaesAccountCredentialOps:
        """Bind the existing provider-neutral account realizer to AWS storage."""
        from raes_account_credentials import RaesAccountCredentialOps

        return RaesAccountCredentialOps(self.account_password, self.account_key, self.delete_account)

    def directory_ops(self) -> RaesDirectorySecretOps:
        """Bind the existing provider-neutral directory realizer to AWS storage."""
        from raes_active_directory import RaesDirectorySecretOps

        return RaesDirectorySecretOps(
            self.domain_dsrm,
            self.domain_authority,
            self.domain_account,
            lambda rid, domain: self.delete(rid, "domain-dsrm", (domain,)),
            lambda rid, domain: self.delete(rid, "domain-authority", (domain,)),
            lambda rid, domain, account: self.delete(rid, "domain-account", (domain, account)),
        )
