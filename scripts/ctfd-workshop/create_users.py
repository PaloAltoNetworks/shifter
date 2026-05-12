#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any

from common import CtfdClient, build_password


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create workshop participant accounts in the standalone CTFd."
    )
    parser.add_argument("--base-url", required=True, help="CTFd base URL, e.g. https://ctf.shifter.example.com")
    parser.add_argument(
        "--token",
        default=os.environ.get("CTFD_TOKEN"),
        help="CTFd admin API token. Defaults to CTFD_TOKEN.",
    )
    parser.add_argument("--csv", required=True, help="Input CSV with at least name,email columns.")
    parser.add_argument(
        "--output",
        help="Optional output CSV to write created credentials and statuses.",
    )
    parser.add_argument(
        "--default-password",
        help="Default password for rows that do not include a password column.",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Ask CTFd to send created users an email with their credentials.",
    )
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Patch existing users instead of skipping them.",
    )
    return parser.parse_args()


def load_rows(csv_path: str) -> list[dict[str, str]]:
    with Path(csv_path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for row in reader:
            cleaned = {key.strip(): (value or "").strip() for key, value in row.items() if key}
            if not cleaned.get("name") or not cleaned.get("email"):
                raise ValueError("each CSV row must contain name and email")
            rows.append(cleaned)
    return rows


def find_user_by_email(client: CtfdClient, email: str) -> dict[str, Any] | None:
    response = client.get("/users", {"view": "admin", "field": "email", "q": email})
    for user in response.get("data", []):
        if user.get("email", "").lower() == email.lower():
            return user
    return None


def write_results(path: str, rows: list[dict[str, str]]) -> None:
    fieldnames = ["name", "email", "password", "status", "user_id", "affiliation"]
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if not args.token:
        raise SystemExit("missing --token and CTFD_TOKEN is not set")

    client = CtfdClient(args.base_url, args.token)
    input_rows = load_rows(args.csv)
    results: list[dict[str, str]] = []

    for row in input_rows:
        email = row["email"]
        password = row.get("password") or args.default_password or build_password()
        affiliation = row.get("affiliation", "")
        existing = find_user_by_email(client, email)

        payload = {
            "name": row["name"],
            "email": email,
            "affiliation": affiliation,
            "verified": True,
            "type": "user",
        }

        if existing:
            if not args.update_existing:
                print(f"skip existing user: {email}")
                results.append(
                    {
                        "name": row["name"],
                        "email": email,
                        "password": "",
                        "status": "skipped-existing",
                        "user_id": str(existing["id"]),
                        "affiliation": affiliation,
                    }
                )
                continue

            payload["password"] = password
            print(f"update user: {email}")
            response = client.patch(f"/users/{existing['id']}", payload)
            user_id = response["data"]["id"]
            status = "updated"
        else:
            payload["password"] = password
            print(f"create user: {email}")
            path = "/users?notify=1" if args.notify else "/users"
            response = client.post(path, payload)
            user_id = response["data"]["id"]
            status = "created"

        results.append(
            {
                "name": row["name"],
                "email": email,
                "password": password,
                "status": status,
                "user_id": str(user_id),
                "affiliation": affiliation,
            }
        )

    if args.output:
        write_results(args.output, results)
        print(f"wrote results: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
