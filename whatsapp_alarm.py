import time
import re
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service

from webdriver_manager.chrome import ChromeDriverManager

import winsound


# ===================== CONFIG =====================

@dataclass
class Config:
    group_name: str
    keywords: List[str]
    poll_seconds: float = 1.0
    alarm_beeps: int = 6
    beep_freq_hz: int = 1400
    beep_ms: int = 300
    wav_path: Optional[str] = None
    chrome_user_data_dir = os.path.join(os.environ["LOCALAPPDATA"], "WhatsAppVibeProfile")


cfg = Config(
    group_name="OH DX-klusteri",
    keywords=["alert", "urgent"],
    poll_seconds=1.0,
    alarm_beeps=6,
    beep_freq_hz=1400,
    beep_ms=300,
    wav_path=None  # Example: r"C:\Windows\Media\Alarm01.wav"
)

# ==================================================


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def keyword_hit(text: str, keywords: List[str]) -> Optional[str]:
    t = normalize(text)
    for kw in keywords:
        if normalize(kw) in t:
            return kw
    return None


def play_alarm(cfg: Config):
    print("🔔 Playing alarm...")
    for _ in range(cfg.alarm_beeps):
        winsound.Beep(cfg.beep_freq_hz, cfg.beep_ms)
        time.sleep(0.05)

    if cfg.wav_path:
        try:
            winsound.PlaySound(cfg.wav_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            print(f"[WARN] Could not play WAV: {e}")


from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import os

def build_driver(cfg):
    chrome_options = Options()

    # Core stability flags (Windows)
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--remote-allow-origins=*")

    # Use a safe absolute profile folder
    profile_path = os.path.abspath(cfg.chrome_user_data_dir)
    chrome_options.add_argument(f"--user-data-dir={profile_path}")

    # Optional: avoid automation detection oddities
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)


def wait_for_whatsapp_ready(driver):
    driver.get("https://web.whatsapp.com/")
    wait = WebDriverWait(driver, 180)

    print("[INFO] Waiting for WhatsApp Web... (scan QR if needed)")
    # Wait until either chat search or chat list appears
    wait.until(
        EC.any_of(
            EC.presence_of_element_located((By.XPATH, "//*[@aria-label='Search input textbox']")),
            EC.presence_of_element_located((By.XPATH, "//div[@role='grid']")),
            EC.presence_of_element_located((By.XPATH, "//div[@data-pre-plain-text]")),
        )
    )
    print("[INFO] WhatsApp appears ready.")


from selenium.common.exceptions import StaleElementReferenceException, TimeoutException

def open_group_chat(driver, group_name: str):
    wait = WebDriverWait(driver, 60)
    print(f"[INFO] Opening group chat: {group_name}")

    # Try a few times because WhatsApp re-renders the list constantly
    for attempt in range(1, 6):
        try:
            # Click the search box (use stable aria label if present, else fallback)
            try:
                search = wait.until(EC.presence_of_element_located(
                    (By.XPATH, "//*[@aria-label='Search input textbox']")
                ))
            except TimeoutException:
                search = wait.until(EC.presence_of_element_located(
                    (By.XPATH, "//div[@contenteditable='true'][@role='textbox']")
                ))

            search.click()
            time.sleep(0.2)
            search.send_keys(Keys.CONTROL, "a")
            search.send_keys(Keys.BACKSPACE)
            search.send_keys(group_name)
            time.sleep(1.0)

            # IMPORTANT: re-locate right before click (prevents stale click)
            chat_xpath = f"//span[@title={repr(group_name)}]"
            wait.until(EC.presence_of_element_located((By.XPATH, chat_xpath)))
            chat = wait.until(EC.element_to_be_clickable((By.XPATH, chat_xpath)))
            chat.click()

            # Wait until message composer exists => chat opened
            wait.until(EC.presence_of_element_located((By.XPATH, "//footer//div[@contenteditable='true']")))
            print(f"[INFO] Group opened successfully on attempt {attempt}.")
            return

        except StaleElementReferenceException:
            print(f"[WARN] Stale element (attempt {attempt}), retrying...")
            time.sleep(0.6)
            continue
        except Exception as e:
            print(f"[WARN] Open group failed (attempt {attempt}): {e}")
            time.sleep(0.8)
            continue

    raise RuntimeError("Could not open group chat after multiple retries. WhatsApp DOM likely changed.")




def scroll_chat_to_bottom(driver):
    """Keep chat at bottom so new messages load into DOM."""
    try:
        box = driver.find_element(By.XPATH, "//footer//div[@contenteditable='true']")
        box.click()
        time.sleep(0.05)
        box.send_keys(Keys.END)
        box.send_keys(Keys.CONTROL, Keys.END)
    except Exception:
        pass


def get_messages(driver):
    """
    Works when data-pre-plain-text exists but selectable-text spans do NOT.
    Returns list of (msg_id, sender, text).
    """
    results = []

    blocks = driver.find_elements(By.XPATH, "//div[@data-pre-plain-text]")
    for b in blocks:
        try:
            meta = (b.get_attribute("data-pre-plain-text") or "").strip()
            # Sender from meta: "[HH:MM, DD/MM/YYYY] Name: "
            sender = "Unknown"
            if "] " in meta:
                after = meta.split("] ", 1)[-1]
                if ": " in after:
                    sender = after.split(": ", 1)[0].strip()

            # IMPORTANT: Use full visible text of the block
            text = (b.text or "").strip()

            # WhatsApp sometimes includes the time or blank lines—filter empty
            if not text:
                continue

            msg_id = f"{meta}|{text}"
            results.append((msg_id, sender, text))

        except Exception:
            continue

    return results


def probe_dom(driver):
    probes = {
        "data-pre-plain-text blocks": "//div[@data-pre-plain-text]",
        "selectable-text spans": "//span[contains(@class,'selectable-text')]/span",
        "any role=application": "//*[@role='application']",
        "message bubble candidates (generic)": "//*[contains(@class,'copyable-text')]",
        "footer composer": "//footer//div[@contenteditable='true']",
    }

    print("\n[PROBE] DOM probe counts:")
    for name, xp in probes.items():
        try:
            n = len(driver.find_elements(By.XPATH, xp))
            print(f"  - {name}: {n}")
        except Exception as e:
            print(f"  - {name}: ERROR {e}")

    # Also print a short snippet of the page title and URL
    print(f"[PROBE] Title: {driver.title}")
    print(f"[PROBE] URL:   {driver.current_url}\n")


def main():
    driver = build_driver(cfg)

    try:
        wait_for_whatsapp_ready(driver)
        time.sleep(1.5)

        open_group_chat(driver, cfg.group_name)
        probe_dom(driver)
        
        # Seed: capture whatever is currently loaded so we only print NEW messages from now on
        seen_ids = set()
        for msg_id, _, _ in get_messages(driver):
            seen_ids.add(msg_id)

        print("[DEBUG] Monitoring started. New messages will print below.\n")

        seen_ids = set()

        # Seed with messages already on screen (so old history isn't dumped)
        for msg_id, sender, text in get_messages(driver):
            seen_ids.add(msg_id)

        print(f"[DEBUG] Seeded {len(seen_ids)} existing messages. Waiting for new ones...\n")

        while True:
            scroll_chat_to_bottom(driver)

            msgs = get_messages(driver)

            # Print new ones immediately (including the first one that arrives)
            new_items = [(mid, s, t) for (mid, s, t) in msgs if mid not in seen_ids]

            for msg_id, sender, text in new_items:
                seen_ids.add(msg_id)

                ts = time.strftime("%H:%M:%S")
                print(f"[{ts}] {sender}: {text}")

                hit = keyword_hit(text, cfg.keywords)
                if hit:
                    print(f"🚨 KEYWORD MATCHED: '{hit}' 🚨")
                    play_alarm(cfg)

            time.sleep(cfg.poll_seconds)
    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user.")
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
