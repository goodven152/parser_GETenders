#!/usr/bin/env python3
"""
parser.py — исправленный парсер тендеров на ge­tender.
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
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.service import Service
from tqdm import tqdm
from webdriver_manager.chrome import ChromeDriverManager

START_URL = "https://tenders.procurement.gov.ge/public/?lang=ge"
PAGE_ROWS = 4

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


def extract_text(file_path: Path) -> str:
    try:
        import textract
        return textract.process(str(file_path)).decode("utf-8", errors="ignore")
    except Exception as exc:
        logging.warning("%s: fallback failed (%s)", file_path.name, exc)
        return ""


def file_contains_keywords(file_path: Path) -> bool:
    text = extract_text(file_path)
    return bool(KEYWORDS_RE.search(text))


def scrape_tenders(max_pages: int | None = None, headless: bool = True) -> List[str]:
    cache_path = Path("visited_ids.txt")
    visited: Set[str] = set(cache_path.read_text().split()) if cache_path.exists() else set()
    hits: List[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        download_dir = Path(tmpdir)
        driver = make_driver(headless=headless, download_dir=download_dir)
        driver.get(START_URL)

        # Фильтр “გამარჯვებული აღმოჩენილია”
        wait_click(driver, (By.ID, "app_donor_id"))
        time.sleep(1)
        wait_click(driver, (By.XPATH, "//option[contains(., 'გამარჯვებული გამოვლენილია')]"))
        time.sleep(1)
        wait_click(driver, (By.ID, "search_btn"))

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
        )

        page_num = 1
        while True:
            logging.info("Page %d", page_num)
            rows = driver.find_elements(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")

            for i in tqdm(range(len(rows)), desc=f"Page {page_num}"):
                # Обновляем список строк
                rows = driver.find_elements(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")
                if i >= len(rows):
                    break

                tender = rows[i]
                tender_id = tender.find_element(By.CSS_SELECTOR, "p strong").text.strip()
                if tender_id in visited:
                    continue
                visited.add(tender_id)

                # Очистка загрузок перед новым тендером
                for f in download_dir.iterdir():
                    f.unlink()

                tender.click()
                try:
                    # Открываем вкладку “документация”
                    wait_click(driver, (By.XPATH, "//a[contains(., 'დოკუმენტაცია')]"))

                    # Скачиваем все файлы из блока .answ-file
                    links = driver.find_elements(By.CSS_SELECTOR, ".answ-file a[target='_blank']")
                    for link in links:
                        href = link.get_attribute("href")
                        driver.execute_script("window.open(arguments[0]);", href)
                        driver.switch_to.window(driver.window_handles[-1])
                        # ждём, пока файл появится в папке (макс. 10 сек)
                        for _ in range(20):
                            if any(download_dir.iterdir()):
                                break
                            time.sleep(0.5)
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])

                    # Проверяем скачанные файлы
                    found = False
                    for dl in download_dir.iterdir():
                        if file_contains_keywords(dl):
                            hits.append(tender_id)
                            found = True
                            break

                    # Возврат к списку
                    wait_click(driver, (By.ID, "back_button_2"))
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
                    )

                except Exception as exc:
                    logging.warning("%s failed: %s", tender_id, exc)
                    # Пытаемся вернуть назад
                    try:
                        wait_click(driver, (By.ID, "back_button_2"))
                        WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
                        )
                    except Exception:
                        logging.error("Не удалось вернуться после ошибки")

            # Лимит страниц
            if max_pages and page_num >= max_pages:
                break

            # Перейти на следующую страницу
            try:
                wait_click(driver, (By.ID, "btn_next"))
                page_num += 1
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
                )
            except Exception:
                break

        driver.quit()

    # Сохраняем кеш посещённых
    cache_path.write_text("\n".join(sorted(visited)))
    return hits


def main(argv: Iterable[str] | None = None):
    parser = argparse.ArgumentParser(description="Georgian tender keyword scraper")
    parser.add_argument("--output", default="found_tenders.json", help="Path to save JSON result")
    parser.add_argument("--max-pages", type=int, help="Stop after N pages")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window")
    parser.add_argument("--reset-cache", action="store_true", help="Удалить кеш перед стартом")
    parser.add_argument("--log", default="INFO", help="Logging level")
    args = parser.parse_args(argv)

    if args.reset_cache:
        cache_file = Path("visited_ids.txt")
        if cache_file.exists():
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
