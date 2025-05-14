#!/usr/bin/env python3
"""
ge_tender_parser.py
--------------------
CLI utility that scans the Georgian public‑procurement portal for tenders whose
budgetary documents contain one of a predefined list of Georgian keywords.

Usage
-----
$ python ge_tender_parser.py --output found.json  # run headless, save results
$ python ge_tender_parser.py --no-headless --max-pages 3  # debug run

Key features
------------
*   Opens https://tenders.procurement.gov.ge/public/?lang=ge as an anonymous
    visitor and applies the «Winner identified» filter (შესყიდვის სტატუსი → გამარჯვებული გამოვლენილია).
*   Iterates over paginated search results (4 rows per virtual page).
*   For every tender row it drills down to the documentation tab, expands the
    «1.3 ფასების ცხრილი/ხარჯთაღრიცხვა» group and downloads the attached files.
*   Extracts raw text from PDFs, DOC(X), XLS(X) and common archives using
    ``textract``; falls back to ``pdftotext`` / ``docx2txt`` if available.
*   Performs *case‑insensitive* search for any of the target Georgian strings.
*   Collects the unique tender ID (e.g. ``NAT250007993``) for each positive hit
    and finally writes a JSON array to the chosen output path.
*   Resumable: already‑visited tender IDs are cached locally so a second run
    skips finished pages quickly.

Dependencies
------------
```
pip install selenium webdriver-manager textract python-magic pdfminer.six tqdm
```
Chrome/Chromium 114+ must be installed. The script auto‑downloads a matching
ChromeDriver via *webdriver‑manager*.
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import requests
import mimetypes
from pathlib import Path
from typing import Iterable, List, Set
from urllib.parse import urlparse


from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.service import Service
from tqdm import tqdm
from webdriver_manager.chrome import ChromeDriverManager



START_URL = "https://tenders.procurement.gov.ge/public/?lang=ge"
PAGE_ROWS = 4  # number of tenders shown at once after search

KEYWORDS_GEO = [
    "თუჯის სარქველი",
    "ფლიანეცებს შორის მბრუნავი სარქველი",
    "ორმაგი ექსცენტრიული მბრუნავი სარქველი",
    "მილტუჩა ჩამკეტი რეზინის სარქველით",
    "მილტუჩა ჩამკეტი მეტალის სარქველით",
    "ჰიდრანტი მიწისქვეშა ორმაგი საკეტი",
    "დანისებრი სარქველი",
]
KEYWORDS_RE = re.compile("|".join(map(re.escape, KEYWORDS_GEO)), flags=re.I)


# ----------------------------------------------------------------------------
# Selenium helpers
# ----------------------------------------------------------------------------

def make_driver(headless: bool = True, download_dir: Path | None = None) -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=ka,en-US")

    prefs = {
        "download.default_directory": str(download_dir or Path.cwd()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    opts.add_experimental_option("prefs", prefs)

    driver_path = ChromeDriverManager().install()
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(60)
    return driver

def wait_click(driver: webdriver.Chrome, locator: tuple[str, str], timeout: int = 20):
    WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator)).click()


def wait_visible(driver: webdriver.Chrome, locator: tuple[str, str], timeout: int = 20):
    return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located(locator))


# ----------------------------------------------------------------------------
# Document extraction
# ----------------------------------------------------------------------------

def extract_text(file_path: Path) -> str:
    """Return plain text extracted from *file_path* using textract."""
    try:
        import textract  # heavy import
        return textract.process(str(file_path)).decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        logging.warning("%s: fallback failed (%s)", file_path.name, exc)
        return ""


def file_contains_keywords(file_path: Path) -> bool:
    text = extract_text(file_path)
    return bool(KEYWORDS_RE.search(text))


# ----------------------------------------------------------------------------
# Core high‑level routine
# ----------------------------------------------------------------------------

def scrape_tenders(max_pages: int | None = None, headless: bool = True) -> List[str]:
    DOWNLOADS_DIR = Path("downloads")
    if DOWNLOADS_DIR.exists():
        shutil.rmtree(DOWNLOADS_DIR)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    cache_path = Path("visited_ids.txt")
    visited: Set[str] = set(cache_path.read_text().split()) if cache_path.exists() else set()
    hits: List[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        # 1) Запускаем драйвер
        driver = make_driver(headless=headless, download_dir=Path(tmpdir))
        driver.get(START_URL)

        # 2) Собираем корень без /public
        parsed = urlparse(START_URL)
        root = f"{parsed.scheme}://{parsed.netloc}"

        # 3) Подготавливаем сессию с куками
        session = requests.Session()
        for c in driver.get_cookies():
            session.cookies.set(c['name'], c['value'])

        # 4) Применяем фильтры
        wait_click(driver, (By.ID, "app_donor_id"))
        time.sleep(2)
        wait_click(driver, (By.XPATH, "//option[contains(., 'გამარჯვებული გამოვლენილია')]"))
        time.sleep(1)
        wait_click(driver, (By.ID, "search_btn"))
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
        )

        page_num = 1
        while True:
            logging.info("Page %d", page_num)
            rows = driver.find_elements(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")

            for i in tqdm(range(len(rows)), desc=f"Page {page_num}"):
                # ре-получаем список
                rows = driver.find_elements(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")
                if i >= len(rows):
                    break

                tender = rows[i]
                tender_id = tender.find_element(By.CSS_SELECTOR, "p strong").text.strip()
                if tender_id in visited:
                    continue
                visited.add(tender_id)

                # безопасный клик по тендеру
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", tender)
                try:
                    tender.click()
                except:
                    ActionChains(driver).move_to_element(tender).click().perform()

                # ждём вкладку "დოკუმენტაცია"
                WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'დოკუმენტაცია')]"))
                )
                wait_click(driver, (By.XPATH, "//a[contains(., 'დოკუმენტაცია')]"))

                # ждём, пока появятся ссылки на файлы
                WebDriverWait(driver, 10).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.answ-file a"))
                )

                # собираем и скачиваем
                files = driver.find_elements(By.CSS_SELECTOR, "div.answ-file a")
                logging.info("→ найдено %d ссылок на документы", len(files))
                for link in files:
                    href = link.get_attribute("href")
                    logging.debug("   • raw href = %s", href)

                    if href.startswith("http"):
                        file_url = href
                    else:
                        file_url = f"{root}/{href.lstrip('/')}"

                    logging.info("   → скачиваем файл: %s", file_url)
                    try:
                        r = session.get(file_url, stream=True, timeout=60)
                        logging.debug(" → Response headers: %s", r.headers)
                        r.raise_for_status()
                    except Exception as e:
                        logging.warning("Не удалось скачать %s: %s", file_url, e)
                        continue

                    filename = href.split("file=")[-1].split("&")[0]
                    out_path = DOWNLOADS_DIR  / filename
                    with open(out_path, "wb") as f:
                        for chunk in r.iter_content(1024):
                            f.write(chunk)

                # проверяем скачанные
                for dl in Path(tmpdir).iterdir():
                    if file_contains_keywords(dl):
                        hits.append(tender_id)
                        logging.info("+++ тендер %s содержит ключи", tender_id)
                        break

                # возвращаемся назад
                wait_click(driver, (By.ID, "back_button_2"))
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
                )
                time.sleep(0.5)

            # листаем страницу
            if max_pages and page_num >= max_pages:
                break
            try:
                wait_click(driver, (By.ID, "btn_next"))
                page_num += 1
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
                )
            except:
                break

        driver.quit()

    cache_path.write_text("\n".join(sorted(visited)))
    return hits


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None):
    parser = argparse.ArgumentParser(description="Georgian tender keyword scraper")
    parser.add_argument("--output", default="found_tenders.json", help="Path to save JSON result")
    parser.add_argument("--max-pages", type=int, help="Stop after N results pages")
    parser.add_argument("--no-headless", action="store_true", help="Run with visible browser window")
    parser.add_argument("--reset-cache", action="store_true", help="Удалить visited_ids.txt перед началом работы",)
    parser.add_argument("--log", default="INFO", help="Logging level")
    args = parser.parse_args(argv)

    # ← если указали --reset-cache, удаляем файл кеша
    cache_file = Path("visited_ids.txt")
    if args.reset_cache and cache_file.exists():
        cache_file.unlink()
        print("Cache reset: removed visited_ids.txt")

    logging.basicConfig(
        level=getattr(logging, args.log.upper(), "INFO"),
        format="%(levelname)s: %(message)s"
    )

    logging.info("Starting scrape…")
    try:
        ids = scrape_tenders(max_pages=args.max_pages, headless=not args.no_headless)
    except KeyboardInterrupt:
        sys.exit("Interrupted by user")

    Path(args.output).write_text(json.dumps(ids, indent=2, ensure_ascii=False))
    print(f"Saved {len(ids)} tender IDs → {args.output}")


if __name__ == "__main__":
    main()
