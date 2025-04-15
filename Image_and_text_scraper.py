import os
import re
import csv
import time
import requests
import sqlite3
from datetime import datetime
from PIL import Image
import pytesseract
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# === Configuration ===
EMAIL = "N.b.gonzalo@gmail.com"
PASSWORD = "Olaolaola-2121"
CSV_FILE = "post_log.csv"
DB_FILE = "signals.db"
IMAGE_DIR = "images"

os.makedirs(IMAGE_DIR, exist_ok=True)

# === Chrome WebDriver Setup ===
options = Options()
options.add_argument("--headless=new")
driver = webdriver.Chrome(service=Service(), options=options)

# === Login ===
def login():
    print(f"[{datetime.now()}] 🔐 Logging in...")
    driver.get("https://www.pricesync.net/user/auth")

    WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.NAME, "email")))
    driver.find_element(By.NAME, "email").send_keys(EMAIL)
    driver.find_element(By.NAME, "password").send_keys(PASSWORD)
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()

    WebDriverWait(driver, 10).until(EC.url_contains("/dashboard"))
    print(f"[{datetime.now()}] ✅ Logged in.")

# === SQLite Initialization ===
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            post_time TEXT,
            title TEXT,
            text TEXT,
            image_url TEXT UNIQUE,
            image_path TEXT,
            symbol TEXT,
            direction TEXT,
            risk_trigger TEXT,
            entry TEXT,
            stop_loss TEXT,
            take_profit TEXT
        )
    """)
    conn.commit()
    conn.close()

# === Parse trade signal ===
def parse_signal(text, image_path=None):
    symbol = None
    direction = None
    risk_trigger = None
    entry = None
    stop_loss = None
    take_profit = None

    lines = text.strip().splitlines()
    first_line = lines[0] if lines else ""

    match = re.match(r'\b([A-Z]{3,6})\b', first_line)
    if match:
        symbol = match.group(1)

    if re.search(r'\b(short|sell|bearish|downside)\b', text, re.IGNORECASE):
        direction = "SELL"
    elif re.search(r'\b(buy|long|bullish|upside)\b', text, re.IGNORECASE):
        direction = "BUY"

    risk_patterns = [
        r'invalidation(?: level)?[:\s]*([^\n,;]+)',
        r'(stop[- ]?loss|risk trigger)[:\s]*([^\n,;]+)',
        r'if .*?close[sd]? (above|below|at) [^\n,;]+',
        r'(above|below|under|over) (resistance|support) at [^\n,;]+'
    ]
    for pattern in risk_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            risk_trigger = match.group(0).strip()
            break

    entry_match = re.search(r"(?:entry|buy at|sell at)[:\s]*\$?(\d+\.?\d*)", text, re.IGNORECASE)
    sl_match = re.search(r"(?:stop[- ]?loss|SL)[:\s]*\$?(\d+\.?\d*)", text, re.IGNORECASE)
    tp_match = re.search(r"(?:take[- ]?profit|TP)[:\s]*\$?(\d+\.?\d*)", text, re.IGNORECASE)

    if entry_match:
        entry = entry_match.group(1)
    if sl_match:
        stop_loss = sl_match.group(1)
    if tp_match:
        take_profit = tp_match.group(1)

    return {
        "symbol": symbol,
        "direction": direction,
        "risk_trigger": risk_trigger,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit
    }

# === Check if image already exists ===
def image_already_saved(image_url):
    image_id = str(hash(image_url)) + ".png"
    return os.path.exists(os.path.join(IMAGE_DIR, image_id))

# === Save to CSV ===
def log_to_csv(data):
    file_exists = os.path.isfile(CSV_FILE)
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(data.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(data)

# === Save to SQLite DB ===
def insert_to_db(data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT OR IGNORE INTO signals (
            timestamp, post_time, title, text, image_url, image_path,
            symbol, direction, risk_trigger, entry, stop_loss, take_profit
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data["timestamp"], data["post_time"], data["title"], data["text"],
        data["image_url"], data["image_path"], data["symbol"], data["direction"],
        data["risk_trigger"], data["entry"], data["stop_loss"], data["take_profit"]
    ))
    conn.commit()
    conn.close()

# === Print summary stats ===
def print_stats():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT direction, COUNT(*) FROM signals GROUP BY direction")
    rows = c.fetchall()
    print("\n📊 Signal Stats:")
    for row in rows:
        print(f"{row[0]}: {row[1]}")
    conn.close()

# === Scrape all posts ===
def scrape_all_posts():
    print(f"[{datetime.now()}] 🔍 Scraping all visible posts...")
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
    time.sleep(3)

    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, "post-card"))
        )
    except:
        print("⚠️ No posts found.")
        return

    posts = driver.find_elements(By.CLASS_NAME, "post-card")
    print(f"📥 Found {len(posts)} post cards")

    for i, post in enumerate(posts):
        try:
            title = post.find_element(By.CSS_SELECTOR, "h4.text-gray-800.fs-3.fw-bold").text.strip()
            text = post.find_element(By.CSS_SELECTOR, "div.text-gray-700").text.strip()
            img_url = post.find_element(By.CSS_SELECTOR, "img.card-rounded-bottom").get_attribute("src")
            post_time = post.find_element(By.CSS_SELECTOR, "span.fw-bold.text-muted.fs-5.ps-1").text.strip()
        except Exception as e:
            print(f"⚠️ Could not parse post: {e}")
            continue

        if image_already_saved(img_url):
            print(f"⏩ Skipping existing image.")
            continue

        # Parse signal
        signal = parse_signal(text)

        # Clean file name
        symbol = signal.get("symbol") or "UNKNOWN"
        clean_title = re.sub(r'\W+', '_', title)[:30]
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{symbol}_{clean_title}.png"
        img_path = os.path.join(IMAGE_DIR, filename)

        # Download image
        try:
            img_data = requests.get(img_url).content
            with open(img_path, "wb") as f:
                f.write(img_data)
            print(f"📸 Saved: {img_path}")
        except Exception as e:
            print(f"❌ Failed to save image: {e}")
            continue

        # Combine full data
        post_data = {
            "timestamp": datetime.now().isoformat(),
            "post_time": post_time,
            "title": title,
            "text": text,
            "image_url": img_url,
            "image_path": img_path,
            "symbol": signal["symbol"],
            "direction": signal["direction"],
            "risk_trigger": signal["risk_trigger"],
            "entry": signal["entry"],
            "stop_loss": signal["stop_loss"],
            "take_profit": signal["take_profit"]
        }

        log_to_csv(post_data)
        insert_to_db(post_data)

# === MAIN ===
if __name__ == "__main__":
    try:
        init_db()
        login()
        scrape_all_posts()
        print_stats()
    finally:
        driver.quit()
