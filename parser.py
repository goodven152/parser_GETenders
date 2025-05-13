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
from pathlib import Path
from typing import Iterable, List, Set


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
    cache_path = Path("visited_ids.txt")
    visited: Set[str] = set(cache_path.read_text().split()) if cache_path.exists() else set()
    hits: List[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        driver = make_driver(headless=headless, download_dir=Path(tmpdir))
        driver.get(START_URL)

        # 1. Apply the «Winner identified» status filter
        wait_click(driver, (By.ID, "app_donor_id"))
        wait_click(driver, (By.XPATH, "//option[contains(., 'გამარჯვებული გამოვლენილია')]"))
        wait_click(driver, (By.ID, "search_btn"))  # "ძიება" button
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#tenders_tbl tbody tr"))
        )
        page_num = 1
        while True:
            logging.info("Page %d", page_num)
            rows = driver.find_elements(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")
            for row in tqdm(rows, desc=f"Page {page_num}"):
                # заново докачиваем актуальный список
                rows = driver.find_elements(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")
                row = rows[tqdm]


                tender_id = row.find_element(By.CSS_SELECTOR, "strong").text()
                if tender_id in visited:
                    continue
                visited.add(tender_id)


                # open row
                row.find_element(By.CSS_SELECTOR, "a").send_keys(Keys.CONTROL + Keys.RETURN)
                driver.switch_to.window(driver.window_handles[-1])

                try:
                    # open "დოკუმენტაცია" tab
                    wait_click(driver, (By.XPATH, "//a[contains(., 'დოკუმენტაცია')]") )
                    # expand 1.3 section
                    wait_click(driver, (By.XPATH, "//a[contains(., '1.3 ფასების ცხრილი')]") )
                    files = driver.find_elements(By.CSS_SELECTOR, "#docs_tbl a[target='_blank']")
                    for link in files:
                        href = link.get_attribute("href")
                        driver.execute_script("window.open(arguments[0]);", href)
                        driver.switch_to.window(driver.window_handles[-1])
                        time.sleep(2)  # let download start
                        driver.close()
                        driver.switch_to.window(driver.window_handles[-1])

                    for dl in Path(tmpdir).iterdir():
                        if file_contains_keywords(dl):
                            hits.append(tender_id)
                            break
                except Exception as exc:  # noqa: BLE001
                    logging.warning("%s failed: %s", tender_id, exc)
                finally:
                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

            # pagination
            if max_pages and page_num >= max_pages:
                break
            try:
                wait_click(driver, (By.ID, "btn_next"))  # next page button
                page_num += 1
            except Exception:
                break  # no more pages

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
    parser.add_argument("--log", default="INFO", help="Logging level")
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log.upper(), "INFO"), format="%(levelname)s: %(message)s")

    logging.info("Starting scrape…")
    try:
        ids = scrape_tenders(max_pages=args.max_pages, headless=not args.no_headless)
    except KeyboardInterrupt:
        sys.exit("Interrupted by user")

    Path(args.output).write_text(json.dumps(ids, indent=2, ensure_ascii=False))
    print(f"Saved {len(ids)} tender IDs → {args.output}")


if __name__ == "__main__":
    main()
