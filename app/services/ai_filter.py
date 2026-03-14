import json
import logging
import time
from typing import Any, Dict, Optional

import httpx


CV_KEYWORDS = [
    "qa",
    "quality assurance",
    "software testing",
    "automation testing",
    "playwright",
    "selenium",
    "api testing",
    "python",
    "manual testing",
    "test engineer",
]


def clean_key(value: Optional[str]) -> str:
    key = (value or "").strip()
    if not key or key.lower() in {"replace_me", "none", "null"}:
        return ""
    return key


def ensure_internet_connectivity(timeout_seconds: float = 8.0) -> None:
    test_urls = [
        "https://web.whatsapp.com",
        "https://openrouter.ai",
        "https://www.google.com/generate_204",
    ]
    errors = []
    for url in test_urls:
        try:
            with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
                response = client.get(url)
            if response.status_code < 500:
                logging.info("Internet check passed via %s (status=%s)", url, response.status_code)
                return
            errors.append(f"{url} -> HTTP {response.status_code}")
        except Exception as exc:
            errors.append(f"{url} -> {exc}")

    raise RuntimeError(
        "Internet connectivity check failed. Please verify network before running automation. "
        f"Checks: {' | '.join(errors)}"
    )


def call_openrouter_api(
    key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    site_url: str,
    site_name: str,
) -> str:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if site_url:
        headers["HTTP-Referer"] = site_url
    if site_name:
        headers["X-OpenRouter-Title"] = site_name

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
    }
    with httpx.Client(timeout=30) as client:
        response = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return json.dumps(data)


def analyze_job_post(
    text: str,
    openrouter_key: str,
    openrouter_model: str,
    openrouter_site_url: str,
    openrouter_site_name: str,
    retries: int = 3,
    initial_delay: float = 2.0,
) -> Dict[str, Any]:
    schema_template = {
        "relevant": False,
        "company": "",
        "role": "",
        "location": "",
        "experience": "",
        "skills": "",
        "contact_email": "",
    }

    system_prompt = "Return valid JSON only. No markdown. No extra keys."
    user_prompt = (
        "You are an assistant that filters WhatsApp job posts.\n"
        f"CV keywords: {CV_KEYWORDS}\n"
        "Return JSON ONLY with keys exactly as:\n"
        '{ "relevant": true/false, "company": "", "role": "", "location": "", '
        '"experience": "", "skills": "", "contact_email": "" }\n'
        "If not a job post or not relevant to keywords, set relevant=false.\n"
        f"Job post text:\n{text}"
    )

    or_key = clean_key(openrouter_key)
    if not or_key:
        raise RuntimeError("No LLM API key configured (OPENROUTER_API_KEY)")

    for attempt in range(1, retries + 1):
        try:
            logging.info("Step: AI analysis attempt %s via OpenRouter.", attempt)
            content = call_openrouter_api(
                key=or_key,
                model=openrouter_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                site_url=openrouter_site_url,
                site_name=openrouter_site_name,
            )
            payload = json.loads(content)
            result = {**schema_template, **payload}
            result["relevant"] = bool(result.get("relevant", False))
            logging.info("Step: AI analysis completed. relevant=%s", result["relevant"])
            return result
        except Exception as exc:
            logging.exception("AI analysis failed on attempt %s: %s", attempt, exc)
            if attempt >= retries:
                return schema_template
            time.sleep(initial_delay * (2 ** (attempt - 1)))

    return schema_template
