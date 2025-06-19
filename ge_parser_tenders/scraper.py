import logging
import mimetypes
import re
import shutil
import tempfile
import time
import socket
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException

from .driver_utils import make_driver, wait_click
from .config import ParserSettings

socket.setdefaulttimeout(60)

# ──────────────────────────── helpers ────────────────────────────

def _filename_from_cd(cd: str | None) -> str | None:
    if not cd:
        return None
    if "filename*" in cd:
        _, value = cd.split("filename*", 1)[1].split("=", 1)
        if "''" in value:
            enc, _, raw = value.partition("''")
            return unquote(raw, encoding=enc, errors="replace")
    match = re.search(r'filename="?([^";]+)', cd)
    if match:
        return match[1]
    return None


_CT_EXT_MAP = {
    "application/pdf": ".pdf",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}

def _ext_from_content_type(ct: str | None) -> str:
    if not ct:
        return ""
    ct = ct.split(";", 1)[0].strip()
    return mimetypes.guess_extension(ct) or _CT_EXT_MAP.get(ct, "")

def _safe_filename(name: str, ext_hint: str = "") -> str:
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", Path(name).stem)
    ext = Path(name).suffix or ext_hint
    return f"{slug}{ext}"

def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 1
    while True:
        new_path = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not new_path.exists():
            return new_path
        i += 1

# ──────────────────────────── main scraper ────────────────────────────

def scrape_and_save_json(settings: ParserSettings, max_pages: int | None = None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    DOWNLOADS_DIR = Path("downloads")
    if DOWNLOADS_DIR.exists():
        shutil.rmtree(DOWNLOADS_DIR)
    DOWNLOADS_DIR.mkdir(exist_ok=True)

    tender_data = []
    with tempfile.TemporaryDirectory() as tmpdir:
        driver = make_driver(headless=settings.headless, download_dir=Path(tmpdir))
        driver.get(str(settings.start_url))

        root = "{uri.scheme}://{uri.netloc}".format(uri=urlparse(str(settings.start_url)))
        session = requests.Session()
        for c in driver.get_cookies():
            session.cookies.set(c["name"], c["value"])

        wait_click(driver, (By.ID, "app_donor_id"))
        wait_click(driver, (By.XPATH, "//option[contains(., 'გამარჯვებული გამოვლენილია')]") )
        wait_click(driver, (By.ID, "search_btn"))
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
        )

        page = 1
        while True:
            logging.info(f"📄 Страница {page}")
            rows = driver.find_elements(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")

            for row in rows:
                tender_id = row.find_element(By.CSS_SELECTOR, "p strong").text.strip()
                row.click()

                try:
                    wait_click(driver, (By.XPATH, "//a[contains(., 'დოკუმენტაცია')]") )
                    WebDriverWait(driver, 10).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.answ-file a"))
                    )
                    links = driver.find_elements(By.CSS_SELECTOR, "div.answ-file a")
                    tender_files = []

                    for link in links:
                        href = link.get_attribute("href")
                        url = href if href.startswith("http") else f"{root}/{href.lstrip('/')}"
                        name = link.text.strip() or Path(url).name

                        resp = session.get(url, stream=True, timeout=30)
                        cd_name = _filename_from_cd(resp.headers.get("Content-Disposition"))
                        name = cd_name or name

                        if "." not in name:
                            name += _ext_from_content_type(resp.headers.get("Content-Type"))

                        file_path = _unique(DOWNLOADS_DIR / _safe_filename(name))
                        with file_path.open("wb") as f:
                            for chunk in resp.iter_content(8192):
                                f.write(chunk)
                        tender_files.append(str(file_path.resolve()))

                    tender_data.append({
                        "tender_id": tender_id,
                        "files": tender_files,
                    })
                except Exception as e:
                    logging.warning(f"❌ Ошибка при скачивании документов: {e}")
                finally:
                    wait_click(driver, (By.ID, "back_button_2"))

            if max_pages and page >= max_pages:
                break
            try:
                _next_page(driver)
                page += 1
            except (TimeoutException, StopIteration):
                break

        driver.quit()

    with open("found_tenders.json", "w", encoding="utf-8") as f:
        json.dump(tender_data, f, ensure_ascii=False, indent=2)
    logging.info("✅ Сохранено в found_tenders.json")

# 🔁 Навигация по страницам (упрощённая)
def _next_page(driver):
    next_btn = driver.find_element(By.ID, "btn_next")
    if not next_btn.is_enabled():
        raise StopIteration("No next page")
    first_row = driver.find_element(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")
    driver.execute_script("arguments[0].click();", next_btn)
    WebDriverWait(driver, 10).until(EC.staleness_of(first_row))
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
    )

if __name__ == "__main__":
    from .config import ParserSettings
    settings = ParserSettings.load()
    scrape_and_save_json(settings, max_pages=settings.max_pages)