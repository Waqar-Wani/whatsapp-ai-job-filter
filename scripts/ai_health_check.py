import json
import os
import argparse
from pathlib import Path
from typing import Dict, Tuple

import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def clean_key(value: str | None) -> str:
    key = (value or "").strip()
    if not key or key.lower() in {"replace_me", "none", "null"}:
        return ""
    return key


def check_openrouter(prompt: str) -> Tuple[bool, str]:
    key = clean_key(os.getenv("OPENROUTER_API_KEY"))
    if not key:
        return False, "SKIP: OPENROUTER_API_KEY not set"

    model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    site_url = (os.getenv("OPENROUTER_SITE_URL") or "").strip()
    site_name = (os.getenv("OPENROUTER_SITE_NAME") or "Job Scrapping - Whatsapp").strip()
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if site_url:
        headers["HTTP-Referer"] = site_url
    if site_name:
        headers["X-OpenRouter-Title"] = site_name

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return True, f"PASS: OpenRouter responded. Sample: {text[:120]}"
    except Exception as exc:
        return False, f"FAIL: OpenRouter error: {exc}"


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description="Check AI provider communication.")
    parser.add_argument(
        "--prompt",
        default='Reply with JSON only: {"ok": true}',
        help="Test input prompt sent to providers.",
    )
    args = parser.parse_args()

    checks = [("OpenRouter", lambda: check_openrouter(args.prompt))]

    print("AI communication health check")
    print("-" * 40)
    any_pass = False
    for _, fn in checks:
        ok, message = fn()
        print(message)
        any_pass = any_pass or ok

    print("-" * 40)
    if any_pass:
        print("RESULT: At least one AI provider is working.")
    else:
        print("RESULT: No AI provider communication succeeded.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
