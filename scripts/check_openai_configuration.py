from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from crypto_paper_trader_api.config import Settings  # noqa: E402


def redact(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+\b", "[REDACTED]", text)
    return text[:600]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely inspect the local OpenAI configuration without printing the secret."
    )
    parser.add_argument(
        "--check-api",
        action="store_true",
        help="Send a token-free authentication check to the OpenAI models endpoint.",
    )
    args = parser.parse_args()

    settings = Settings()
    key = settings.openai_api_key
    print(f"Project .env: {settings.project_env_file}")
    print(f"Project .env exists: {settings.project_env_file.is_file()}")
    print(f"Effective key source: {settings.openai_api_key_source}")
    print(f"OPENAI_API_KEY configured: {bool(key)}")
    print(f"Key format looks plausible: {bool(key and key.startswith('sk-') and len(key) >= 20)}")

    if not args.check_api:
        print("API check skipped. Add --check-api to validate authentication.")
        return 0
    if not key:
        print("API check failed: OPENAI_API_KEY is not configured.")
        return 2

    try:
        with httpx.Client(timeout=settings.adaptive_research_web_timeout_seconds) as client:
            response = client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
    except httpx.HTTPError as exc:
        print(f"API check failed before receiving a response: {type(exc).__name__}: {exc}")
        return 3

    print(f"OpenAI HTTP status: {response.status_code}")
    if response.is_success:
        print("OpenAI authentication check: OK")
        return 0

    code = "unknown"
    error_type = "unknown"
    message = response.text
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            code = str(error.get("code") or error.get("type") or "unknown")
            error_type = str(error.get("type") or "unknown")
            message = str(error.get("message") or message)
    except json.JSONDecodeError:
        pass

    print(f"OpenAI error code: {code}")
    print(f"OpenAI error type: {error_type}")
    print(f"OpenAI error detail: {redact(message)}")
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
