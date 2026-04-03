import logging
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.sync_api import BrowserContext, Page, TimeoutError, sync_playwright

from app.core.constants import DATA_DIR, SESSION_DIR


def wait_for_whatsapp_login(page: Page) -> None:
    logging.info("Step: Waiting for WhatsApp login/session.")
    try:
        page.wait_for_selector("div[aria-label='Chat list']", timeout=120000)
        logging.info("Step: WhatsApp session is active.")
        return
    except TimeoutError:
        logging.info("WhatsApp chat list not found yet. Waiting for manual QR login.")

    page.wait_for_selector("div[aria-label='Chat list']", timeout=300000)
    logging.info("Step: Manual QR login completed.")


def find_search_input(page: Page):
    selectors = [
        "input[role='textbox'][aria-label='Search or start a new chat']",
        "input[role='textbox'][aria-label='Search or start new chat']",
        "input[aria-label='Search or start a new chat']",
        "input[aria-label='Search or start new chat']",
        "input[placeholder='Search or start a new chat']",
        "input[placeholder='Search or start new chat']",
        "input[role='textbox'][aria-label*='Search']",
        "div[role='textbox'][aria-label='Search input textbox']",
        "div[role='textbox'][aria-label='Search or start a new chat']",
        "div[role='textbox'][aria-label='Search or start new chat']",
        "div[contenteditable='true'][data-tab='3']",
        "div[contenteditable='true'][data-tab='10']",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        if locator.count() > 0 and locator.is_visible():
            return locator
    try:
        debug_path = DATA_DIR / "search_input_not_found.png"
        page.screenshot(path=str(debug_path), full_page=True)
        logging.warning("Saved debug screenshot: %s", debug_path)
    except Exception:
        pass
    raise RuntimeError("Could not find WhatsApp search input.")


def open_target_group(page: Page, group_name: str) -> None:
    def normalize(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip()).lower()

    def is_group_open() -> bool:
        target = normalize(group_name)
        direct = page.locator(f"header span[title='{group_name}']").first
        if direct.count() > 0 and direct.is_visible():
            return True

        headers = page.locator("header")
        count = min(headers.count(), 6)
        for i in range(count):
            header = headers.nth(i)
            if not header.is_visible():
                continue
            try:
                text = normalize(header.inner_text(timeout=800))
            except Exception:
                continue
            if target in text:
                return True
        return False

    logging.info("Step: Searching for WhatsApp group '%s'.", group_name)
    if is_group_open():
        logging.info("Step: Group '%s' already open.", group_name)
        return

    search_input = find_search_input(page)
    try:
        search_input.fill(group_name)
    except Exception as exc:
        logging.warning("Search input direct fill failed, using keyboard focus fallback: %s", exc)
        focused = False
        for combo in ("Control+K", "Meta+K"):
            try:
                page.keyboard.press(combo)
                focused = True
                break
            except Exception:
                continue
        if not focused:
            try:
                search_input.click(timeout=2000)
            except Exception:
                pass
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
        page.keyboard.type(group_name, delay=40)

    page.wait_for_timeout(700)
    row = page.locator("div[aria-label='Chat list'] span[title]").filter(
        has_text=group_name
    ).first
    if row.count() > 0 and row.is_visible():
        try:
            row.click(force=True, timeout=4000)
        except Exception:
            pass
    else:
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")

    page.wait_for_timeout(2000)
    if is_group_open():
        logging.info("Step: Group '%s' opened.", group_name)
        return

    try:
        headers = page.locator("header")
        observed = []
        for i in range(min(headers.count(), 4)):
            header = headers.nth(i)
            if header.is_visible():
                observed.append(header.inner_text(timeout=500).strip().replace("\n", " | "))
        logging.warning("Header texts seen before failure: %s", observed)
    except Exception:
        pass

    raise RuntimeError(f"Could not open WhatsApp group: {group_name}")


def parse_pre_plain_text(pre_plain_text: str) -> Optional[Dict[str, Any]]:
    match = re.match(
        r"^\[(?P<time>[^,\]]+),\s(?P<date>[^\]]+)\]\s(?P<sender>.*?):\s?$",
        pre_plain_text.strip(),
    )
    if not match:
        return None

    time_part = match.group("time").strip()
    date_part = match.group("date").strip()
    sender = match.group("sender").strip()
    combined = f"{date_part} {time_part}"

    # Prefer day-first formats for international dates (e.g. 2/4/2026 = 2 April 2026)
    date_formats = [
        "%d/%m/%Y %I:%M %p",
        "%d/%m/%y %I:%M %p",
        "%d/%m/%Y %H:%M",
        "%d/%m/%y %H:%M",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%y %I:%M %p",
        "%m/%d/%Y %H:%M",
        "%m/%d/%y %H:%M",
    ]
    for fmt in date_formats:
        try:
            parsed_dt = datetime.strptime(combined, fmt)
            return {"sender": sender, "timestamp": parsed_dt}
        except ValueError:
            continue

    return None


def scrape_messages(page: Page) -> List[Dict[str, Any]]:
    logging.info("Step: Scraping currently loaded WhatsApp messages from chat view.")
    raw_messages = page.evaluate(
        """
        () => {
          const items = [];
          const nodes = document.querySelectorAll("div[data-pre-plain-text]");
          nodes.forEach((node) => {
            const pre = node.getAttribute("data-pre-plain-text") || "";
            const textParts = [];
            const spans = node.querySelectorAll("span.selectable-text span");
            spans.forEach((s) => {
              const txt = (s.innerText || "").trim();
              if (txt) textParts.push(txt);
            });
            if (!textParts.length) {
              const fallback = (node.innerText || "").trim();
              if (fallback) textParts.push(fallback);
            }
            items.push({
              pre_plain_text: pre,
              text: textParts.join("\\n").trim(),
            });
          });
          return items;
        }
        """
    )

    parsed_messages: List[Dict[str, Any]] = []
    for item in raw_messages:
        parsed = parse_pre_plain_text(item.get("pre_plain_text", ""))
        text = (item.get("text") or "").strip()
        if not parsed or not text:
            continue
        parsed_messages.append(
            {
                "sender": parsed["sender"],
                "timestamp": parsed["timestamp"],
                "text": text,
            }
        )

    parsed_messages.sort(key=lambda message: message["timestamp"])
    logging.info("Step: Scraped %s messages from current viewport.", len(parsed_messages))
    return parsed_messages


def expand_truncated_messages(page: Page) -> int:
    expanded = page.evaluate(
        """
        () => {
          const candidates = Array.from(document.querySelectorAll("button, div[role='button'], span"));
          let clicked = 0;

          for (const el of candidates) {
            const txt = (el.textContent || "").trim().toLowerCase();
            if (!txt) continue;

            const isReadMore =
              txt === "read more" ||
              txt.endsWith("read more") ||
              txt.includes("...read more");

            if (!isReadMore) continue;
            if (!(el instanceof HTMLElement)) continue;

            const style = window.getComputedStyle(el);
            if (style.display === "none" || style.visibility === "hidden") continue;

            el.click();
            clicked += 1;
          }
          return clicked;
        }
        """
    )
    return int(expanded or 0)


def scroll_chat_up(page: Page) -> Dict[str, Any]:
    return page.evaluate(
        """
        () => {
          const all = Array.from(document.querySelectorAll("div"));
          const candidates = all.filter((el) => {
            const style = window.getComputedStyle(el);
            const overflowY = style.overflowY;
            const canScroll = (overflowY === "auto" || overflowY === "scroll");
            const hasMessages = !!el.querySelector("div[data-pre-plain-text]");
            return canScroll && el.scrollHeight > el.clientHeight && hasMessages;
          });

          if (!candidates.length) {
            return { found: false };
          }

          const container = candidates.sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
          const before = container.scrollTop;
          const step = Math.max(300, Math.floor(container.clientHeight * 0.9));
          container.scrollTop = Math.max(0, before - step);
          const after = container.scrollTop;

          return {
            found: true,
            before,
            after,
            at_top: after <= 0,
            scroll_height: container.scrollHeight,
            client_height: container.clientHeight,
          };
        }
        """
    )


def message_dedup_key(message: Dict[str, Any]) -> str:
    return (
        f"{message['sender']}|"
        f"{message['timestamp'].isoformat()}|"
        f"{message['text'].strip()}"
    )


def deduplicate_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for message in messages:
        key = message_dedup_key(message)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(message)
    return deduped


def scrape_all_loaded_messages(page: Page, scroll_duration_seconds: int = 30) -> List[Dict[str, Any]]:
    logging.info(
        "Step: Starting scroll-back to load older WhatsApp messages for %s seconds.",
        scroll_duration_seconds,
    )
    all_messages: List[Dict[str, Any]] = []
    start_time = time.time()
    round_idx = 0

    while (time.time() - start_time) < scroll_duration_seconds:
        round_idx += 1
        expanded_now = expand_truncated_messages(page)
        if expanded_now:
            logging.info("Step: Expanded %s truncated message(s).", expanded_now)
            page.wait_for_timeout(250)

        all_messages.extend(scrape_messages(page))
        unique_count = len(deduplicate_messages(all_messages))
        metrics = scroll_chat_up(page)
        elapsed = int(time.time() - start_time)
        logging.info(
            "Step: Scroll round %s | elapsed=%ss | unique_messages=%s | at_top=%s",
            round_idx,
            elapsed,
            unique_count,
            metrics.get("at_top"),
        )

        if not metrics.get("found"):
            logging.info("Step: Could not find chat scroll container. Stopping scroll loop.")
            break
        if metrics.get("at_top"):
            logging.info("Step: Reached top of chat history.")
            break

        page.wait_for_timeout(900)

    expanded_final = expand_truncated_messages(page)
    if expanded_final:
        logging.info("Step: Final expansion clicked %s message(s).", expanded_final)
        page.wait_for_timeout(250)

    deduped = deduplicate_messages(all_messages)
    deduped.sort(key=lambda message: message["timestamp"])
    logging.info("Step: Total unique messages after scroll-back: %s", len(deduped))
    return deduped


def _cleanup_browser_lock() -> None:
    """Clean up stale browser lock files and processes."""
    try:
        # Kill any lingering Chrome processes
        if os.name == 'nt':  # Windows
            subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], 
                         capture_output=True, timeout=5)
        else:  # Unix/Linux/Mac
            subprocess.run(["pkill", "-9", "-f", "chrome"], 
                         capture_output=True, timeout=5)
        
        # Remove lock files
        for lock_file in SESSION_DIR.glob("*LOCK*"):
            try:
                lock_file.unlink()
                logging.debug("Removed lock file: %s", lock_file)
            except Exception as e:
                logging.debug("Failed to remove lock file %s: %s", lock_file, e)
    except Exception as e:
        logging.debug("Browser cleanup encountered error: %s", e)


def _launch_persistent_context_with_retry(playwright, max_retries: int = 3, retry_delay: float = 2.0):
    """Launch persistent context with retry logic for lock file errors."""
    for attempt in range(max_retries):
        try:
            logging.info("Step: Launching Playwright persistent context (attempt %d/%d).", attempt + 1, max_retries)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(SESSION_DIR),
                headless=False,
            )
            return context
        except Exception as e:
            error_msg = str(e)
            is_lock_error = "ProcessSingleton" in error_msg or "Lock file" in error_msg or "Error code: 32" in error_msg
            
            if is_lock_error and attempt < max_retries - 1:
                logging.warning("Browser lock detected on attempt %d. Cleaning up and retrying in %.1f seconds...", 
                              attempt + 1, retry_delay)
                _cleanup_browser_lock()
                time.sleep(retry_delay)
            else:
                raise


def get_all_messages(group_name: str) -> List[Dict[str, Any]]:
    with sync_playwright() as playwright:
        context: BrowserContext = _launch_persistent_context_with_retry(playwright)
        page = context.pages[0] if context.pages else context.new_page()

        logging.info("Step: Opening https://web.whatsapp.com")
        page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")
        wait_for_whatsapp_login(page)
        open_target_group(page, group_name)
        page.wait_for_timeout(2500)
        messages = scrape_all_loaded_messages(page)
        logging.info("Step: Closing Playwright browser context.")
        context.close()

    return messages
