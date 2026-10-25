"""Bounded JSON object parser for closed, credential-bearing management APIs."""

from typing import IO

from rest_framework.exceptions import ParseError
from rest_framework.parsers import BaseParser

from shared.model_access import ContractError
from shared.model_access.messages import JsonObject, strict_json


class ClosedJSONParser(BaseParser):
    """Reject duplicate members before serializer validation can lose them."""

    media_type = "application/json"
    max_bytes = 65_536

    def parse(
        self, stream: IO[bytes], media_type: str | None = None, parser_context: dict[str, object] | None = None
    ) -> JsonObject:
        try:
            return strict_json(stream.read(self.max_bytes + 1), limit=self.max_bytes)
        except (ContractError, ValueError):
            raise ParseError("Invalid JSON object") from None


class ModelSelectionJSONParser(ClosedJSONParser):
    """Bound launch/event configuration while preserving duplicate-key checks."""

    max_bytes = 1_000_000
