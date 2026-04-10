import json
import logging
import re
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


def parse_llm_json(content: Any) -> Dict[str, Any]:
    if isinstance(content, dict):
        return content

    text = str(content or "").strip()
    if not text:
        raise ValueError("LLM returned empty content")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        return json.loads(fenced_match.group(1))

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError(f"LLM did not return parseable JSON. Raw content: {text[:300]}")


def ensure_internet_connectivity(timeout_seconds: float = 8.0) -> None:
    test_urls = [
        "https://web.whatsapp.com",
        "https://openrouter.ai",
        "https://api.groq.com",
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
    max_attempts: int = 4,
    initial_delay: float = 1.5,
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

    retry_status = {429, 500, 502, 503, 504}
    for attempt in range(1, max_attempts + 1):
        try:
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

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            logging.warning("OpenRouter API returned %s (attempt %s/%s): %s", status_code, attempt, max_attempts, exc)
            if status_code == 402:
                raise RuntimeError("OpenRouter payment required (402). Update billing / API plan.")
            if attempt < max_attempts and status_code in retry_status:
                time.sleep(initial_delay * (2 ** (attempt - 1)))
                continue
            raise

        except httpx.RequestError as exc:
            logging.warning("OpenRouter request error (attempt %s/%s): %s", attempt, max_attempts, exc)
            if attempt < max_attempts:
                time.sleep(initial_delay * (2 ** (attempt - 1)))
                continue
            raise

        except Exception as exc:
            logging.error("Unexpected OpenRouter error (attempt %s/%s): %s", attempt, max_attempts, exc)
            if attempt < max_attempts:
                time.sleep(initial_delay * (2 ** (attempt - 1)))
                continue
            raise


def call_groq_api(
    key: str,
    model: str,
    system_prompt: str,
    prompt: str,
    max_attempts: int = 4,
    initial_delay: float = 1.5,
) -> str:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"]
            return json.dumps(data)

        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            logging.warning("Groq API returned %s (attempt %s/%s): %s", status_code, attempt, max_attempts, exc)
            if status_code == 429 and attempt < max_attempts:
                delay = 30.0 * (2 ** (attempt - 1))
                logging.info("Groq rate limited; waiting %.0f seconds before retry.", delay)
                time.sleep(delay)
                continue
            if attempt < max_attempts and status_code in {500, 502, 503, 504}:
                time.sleep(initial_delay * (2 ** (attempt - 1)))
                continue
            raise

        except httpx.RequestError as exc:
            logging.warning("Groq request error (attempt %s/%s): %s", attempt, max_attempts, exc)
            if attempt < max_attempts:
                time.sleep(initial_delay * (2 ** (attempt - 1)))
                continue
            raise

        except Exception as exc:
            logging.error("Unexpected Groq error (attempt %s/%s): %s", attempt, max_attempts, exc)
            if attempt < max_attempts:
                time.sleep(initial_delay * (2 ** (attempt - 1)))
                continue
            raise


def analyze_job_post(
    text: str,
    openrouter_key: str,
    openrouter_model: str,
    openrouter_site_url: str,
    openrouter_site_name: str,
    groq_api_key: str,
    groq_model: str,
    retries: int = 3,
    initial_delay: float = 2.0,
) -> Dict[str, Any]:
    schema_template = {
        "company": "",
        "role": "",
        "location": "",
        "experience": "",
        "skills": "",
        "contact_email": "",
    }

    system_prompt = "Return valid JSON only. No markdown. No extra keys."
    user_prompt = (
        "You are an assistant that parses WhatsApp job posts.\n"
        f"CV keywords: {CV_KEYWORDS}\n"
        "Return JSON ONLY with keys exactly as:\n"
        '{ "company": "", "role": "", "location": "", '
        '"experience": "", "skills": "", "contact_email": "" }\n'
        "If the text is not a job post, return all keys with empty strings.\n"
        f"Job post text:\n{text}"
    )

    or_key = clean_key(openrouter_key)
    groq_key = clean_key(groq_api_key)
    if not or_key and not groq_key:
        raise RuntimeError("No LLM API key configured (OPENROUTER_API_KEY or GROQ_API_KEY)")

    for attempt in range(1, retries + 1):
        try:
            if groq_key:
                logging.info("Step: AI analysis attempt %s via Groq.", attempt)
                content = call_groq_api(
                    key=groq_key,
                    model=groq_model,
                    system_prompt=system_prompt,
                    prompt=user_prompt,
                )
            else:
                logging.info("Step: AI analysis attempt %s via OpenRouter.", attempt)
                content = call_openrouter_api(
                    key=or_key,
                    model=openrouter_model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    site_url=openrouter_site_url,
                    site_name=openrouter_site_name,
                )

            payload = parse_llm_json(content)
            result = {**schema_template, **payload}
            logging.info("Step: AI analysis completed for message.")
            return result
        except Exception as exc:
            logging.exception("AI analysis failed on attempt %s: %s", attempt, exc)
            if attempt >= retries:
                return schema_template
            time.sleep(initial_delay * (2 ** (attempt - 1)))

    return schema_template
