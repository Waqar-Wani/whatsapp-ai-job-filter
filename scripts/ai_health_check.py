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


def format_http_error(provider: str, exc: httpx.HTTPStatusError) -> str:
    status_code = exc.response.status_code
    body = exc.response.text.strip()
    detail = f"HTTP {status_code}"
    if body:
        detail = f"{detail} | {body[:300]}"
    return f"FAIL: {provider} error: {detail}"


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
        "max_tokens": 32,
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
    except httpx.HTTPStatusError as exc:
        return False, format_http_error("OpenRouter", exc)
    except Exception as exc:
        return False, f"FAIL: OpenRouter error: {exc}"


def check_groq(prompt: str) -> Tuple[bool, str]:
    key = clean_key(os.getenv("GROQ_API_KEY"))
    if not key:
        return False, "SKIP: GROQ_API_KEY not set"

    model = os.getenv("GROQ_MODEL", "llama3-8b-8192")
    headers: Dict[str, str] = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 32,
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        return True, f"PASS: Groq responded. Sample: {text[:120]}"
    except httpx.HTTPStatusError as exc:
        return False, format_http_error("Groq", exc)
    except Exception as exc:
        return False, f"FAIL: Groq error: {exc}"


def check_gemini(prompt: str) -> Tuple[bool, str]:
    key = clean_key(os.getenv("GOOGLE_AI_KEY"))
    if not key:
        return False, "SKIP: GOOGLE_AI_KEY not set"

    model = os.getenv("GOOGLE_AI_MODEL", "gemini-flash-latest")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                ]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 32,
        },
    }

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates") or []
        parts = (
            candidates[0].get("content", {}).get("parts", [])
            if candidates
            else []
        )
        text = parts[0].get("text", "") if parts else json.dumps(data)
        return True, f"PASS: Gemini responded. Sample: {text[:120]}"
    except httpx.HTTPStatusError as exc:
        return False, format_http_error("Gemini", exc)
    except Exception as exc:
        return False, f"FAIL: Gemini error: {exc}"


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description="Check AI provider communication.")
    parser.add_argument(
        "--prompt",
        default='Reply with JSON only: {"ok": true}',
        help="Test input prompt sent to providers.",
    )
    args = parser.parse_args()

    checks = [
        ("OpenRouter", lambda: check_openrouter(args.prompt)),
        ("Groq", lambda: check_groq(args.prompt)),
        ("Gemini", lambda: check_gemini(args.prompt)),
    ]

    print("AI communication health check")
    print("-" * 40)
    any_pass = False
    for name, fn in checks:
        ok, message = fn()
        print(f"{name}: {message}")
        any_pass = any_pass or ok

    print("-" * 40)
    if any_pass:
        print("RESULT: At least one AI provider is working.")
    else:
        print("RESULT: No AI provider communication succeeded.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
