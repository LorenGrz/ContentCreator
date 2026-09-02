"""One-time local helper: mint a Google Calendar refresh token and push the
three OAuth values into SSM Parameter Store as SecureStrings.

Run this once on your machine (it opens a browser); the Lambda then refreshes
the token silently forever using ``calendar_client._build_service``.

Prerequisites
-------------
1. In Google Cloud Console create an OAuth client of type **Desktop app** and
   download its JSON (``client_secret_*.json``).
2. Enable the **Google Calendar API** for that project.
3. Local AWS credentials with ``ssm:PutParameter`` on ``/content-creator/*``.

Usage
-----
    python scripts/google_oauth_bootstrap.py --client-secret ~/Downloads/client_secret.json

    # print the refresh token instead of writing to SSM
    python scripts/google_oauth_bootstrap.py --client-secret ... --dry-run

Only ``google-auth-oauthlib`` (already in requirements) and ``boto3`` are used.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

# Read-only: matches _SCOPES in src/ingestion/calendar_client.py.
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

SSM_PREFIX = "/content-creator"
PARAM_CLIENT_ID = f"{SSM_PREFIX}/google-client-id"
PARAM_CLIENT_SECRET = f"{SSM_PREFIX}/google-client-secret"
PARAM_REFRESH_TOKEN = f"{SSM_PREFIX}/google-refresh-token"


def _run_flow(client_secret_path: pathlib.Path):
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    # Force a refresh token even if this client was authorised before.
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
        authorization_prompt_message="Opening a browser to authorise Calendar read-only access…",
        success_message="Done. You can close this tab and return to the terminal.",
    )
    if not creds.refresh_token:
        sys.exit(
            "No refresh token returned. Revoke the app's access at "
            "https://myaccount.google.com/permissions and run this again."
        )
    return creds


def _client_id_secret(client_secret_path: pathlib.Path) -> tuple[str, str]:
    data = json.loads(client_secret_path.read_text())
    node = data.get("installed") or data.get("web") or {}
    return node["client_id"], node["client_secret"]


def _put_ssm(name: str, value: str, region: str | None) -> None:
    import boto3

    client = boto3.client("ssm", region_name=region) if region else boto3.client("ssm")
    client.put_parameter(Name=name, Value=value, Type="SecureString", Overwrite=True)
    print(f"  wrote {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client-secret",
        required=True,
        type=pathlib.Path,
        help="Path to the Desktop-app OAuth client JSON from Google Cloud Console.",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="AWS region for SSM (defaults to the environment / profile).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the values instead of writing them to SSM.",
    )
    args = parser.parse_args()

    if not args.client_secret.is_file():
        sys.exit(f"client secret file not found: {args.client_secret}")

    client_id, client_secret = _client_id_secret(args.client_secret)
    creds = _run_flow(args.client_secret)

    if args.dry_run:
        print("\n--- dry run: nothing written ---")
        print(f"{PARAM_CLIENT_ID}     = {client_id}")
        print(f"{PARAM_CLIENT_SECRET} = {client_secret}")
        print(f"{PARAM_REFRESH_TOKEN} = {creds.refresh_token}")
        return

    print("\nWriting SSM SecureString parameters:")
    _put_ssm(PARAM_CLIENT_ID, client_id, args.region)
    _put_ssm(PARAM_CLIENT_SECRET, client_secret, args.region)
    _put_ssm(PARAM_REFRESH_TOKEN, creds.refresh_token, args.region)
    print("\nCalendar ingestion is ready.")


if __name__ == "__main__":
    main()
