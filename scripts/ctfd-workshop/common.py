#!/usr/bin/env python3
from __future__ import annotations

import json
import secrets
import string
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def build_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class CtfdClient:
    def __init__(self, base_url: str, token: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
            "User-Agent": "shifter-ctfd-workshop/1.0",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | list[Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/api/v1{path}"
        if query:
            query_string = urllib.parse.urlencode(
                {
                    key: value
                    for key, value in query.items()
                    if value is not None
                },
                doseq=True,
            )
            if query_string:
                url = f"{url}?{query_string}"

        request_body = None
        if body is not None:
            request_body = json.dumps(body).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=request_body,
            headers=self.headers,
            method=method.upper(),
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"CTFd API {method.upper()} {path} failed with HTTP {exc.code}: {details}"
            ) from exc

        if payload.get("success") is False:
            raise RuntimeError(
                f"CTFd API {method.upper()} {path} returned an error: {payload}"
            )
        return payload

    def get(self, path: str, query: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("GET", path, query=query)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", path, body=body)

    def patch(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("PATCH", path, body=body)

    def delete(self, path: str) -> dict[str, Any]:
        return self.request("DELETE", path)
