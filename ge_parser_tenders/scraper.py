from __future__ import annotations

"""
scraper.py ― грузинские тендеры
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* проходит по страницам сайта, кликает «დოკუმენტაცია»
* скачивает все прикреплённые файлы
* даёт им читаемые ASCII‑имена (slug‑ified), чтобы внешние CLI‑утилиты
  вроде *pdftotext* не спотыкались о юникод‑пути
* ищет в документах ключевые слова и сохраняет ID тендера,
  если хотя бы один файл «срабатывает»

ВЕРСИЯ 2025‑05‑18
----------------
• Исправлена навигация по страницам: кнопка «Next» иногда не срабатывала,
  из‑за чего парсер обрабатывал только первую страницу. Теперь мы ждём
  обновления таблицы через EC.staleness_of и проверяем, что кнопка не
  отключена.
"""

import logging
import mimetypes
import re
import shutil
import tempfile
import time
import socket
from pathlib import Path
from typing import List, Set
from urllib.parse import unquote, urlparse

import requests
from selenium.common.exceptions import (
    ElementNotInteractableException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.remote.webelement import WebElement
from slugify import slugify
from tqdm import tqdm


from .config import ParserSettings
from .memory_manager import MemoryManager
from .driver_utils import make_driver, wait_click
from .extractor import file_contains_keywords


# ---------------------------------------------------------------------------
#                               helpers
# ---------------------------------------------------------------------------
socket.setdefaulttimeout(60)
_CD_FILENAME_RX = re.compile(
    r"""filename\*?          # filename или filename*
        (?:=[^']*'')?        # =utf-8''  (может отсутствовать)
        ["']?                # возможная кавычка
        (?P<name>[^";]+)     # собственно имя
    """,
    re.I | re.X,
)


def _decode_maybe_utf8(s: str) -> str:
    """Попытка декодировать заголовок, пришедший битым UTF‑8."""
    try:
        return s.encode("latin1").decode("utf-8")
    except UnicodeDecodeError:
        return s


def _filename_from_cd(cd: str | None) -> str | None:
    if not cd:
        return None

    # RFC 5987 — filename*=utf-8''%E1%83%93%E1%83%90…
    if "filename*" in cd:
        _, value = cd.split("filename*", 1)[1].split("=", 1)
        if "''" in value:
            enc, _, raw = value.partition("''")
            return unquote(raw, encoding=enc, errors="replace")

    # filename="დანართი.pdf"
    m = _CD_FILENAME_RX.search(cd)
    if m:
        name = m["name"].strip().strip('"')
        return _decode_maybe_utf8(name)

    return None


_CT_EXT_MAP = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/html": ".html",
    "application/zip": ".zip",
}


def _ext_from_content_type(ct: str | None) -> str:
    if not ct:
        return ""
    ct = ct.split(";", 1)[0].strip()
    return mimetypes.guess_extension(ct) or _CT_EXT_MAP.get(ct, "")


# ── безопасное ASCII‑имя + уникальность ────────────────────────────────

def _safe_filename(raw: str, ext_hint: str = "") -> str:
    stem, ext = Path(raw).stem, Path(raw).suffix or ext_hint
    slug = slugify(stem, lowercase=False, separator="_")
    if not slug:
        slug = "file"
    return f"{slug}{ext}"


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, ext = path.stem, path.suffix
    idx = 1
    while True:
        candidate = path.with_name(f"{stem}_{idx}{ext}")
        if not candidate.exists():
            return candidate
        idx += 1


# ── пагинация ──────────────────────────────────────────────────────────

def _has_next_page(driver) -> bool:
    """Return True if the «Next» button is enabled."""
    try:
        next_btn = driver.find_element(By.ID, "btn_next")
        disabled = (
            not next_btn.is_enabled()
            or "ui-state-disabled" in next_btn.get_attribute("class" or "")
            or next_btn.get_attribute("disabled")
        )
        return not disabled
    except Exception:
        return False


def _next_page(driver, timeout: int = 30):
    """Click «Next» and wait for the table to refresh."""
    if not _has_next_page(driver):
        raise StopIteration("no next page")

    pager = driver.find_element(By.CSS_SELECTOR, ".pager")
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", pager)
    next_btn = driver.find_element(By.ID, "btn_next")

    # save reference to the first row — we'll wait until it's stale
    first_row = driver.find_element(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")

    driver.execute_script("arguments[0].click();", next_btn)

    # wait until previous rows become stale → table was rebuilt
    WebDriverWait(driver, timeout).until(EC.staleness_of(first_row))
    # …and new rows appear
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
    )


# ── безопасный клик по строке ──────────────────────────────────────────

def safe_click(driver, element, retries: int = 3):
    for _ in range(retries):
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            WebDriverWait(driver, 10).until(lambda d: element.is_displayed() and element.is_enabled())
            element.click()
            return
        except (StaleElementReferenceException, ElementNotInteractableException):
            time.sleep(0.5)
    # финальная попытка – JavaScript‑клик
    driver.execute_script("arguments[0].click();", element)


# ---------------------------------------------------------------------------
#                               main scraper
# ---------------------------------------------------------------------------

def scrape_tenders(max_pages: int | None = None, *, headless: bool = True, settings: ParserSettings,) -> List[str]:
    """Возвращает список ID тендеров, в чьих документах найдены ключевые слова."""
    memory_manager = MemoryManager(
        warning_threshold_mb=settings.memory_warning_threshold_mb,
        critical_threshold_mb=settings.memory_critical_threshold_mb,
        gc_interval=settings.gc_interval_seconds
    )
    hits: List[str] = []
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    DOWNLOADS_DIR = Path("downloads")
    if DOWNLOADS_DIR.exists():
        shutil.rmtree(DOWNLOADS_DIR)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    cache_path = Path("visited_ids.txt")
    visited: Set[str] = set(cache_path.read_text().split()) if cache_path.exists() else set()

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            driver = make_driver(headless=headless, download_dir=Path(tmpdir))
            driver.get(str(settings.start_url))               # ← cast to str

            root = "{uri.scheme}://{uri.netloc}".format(uri=urlparse(str(settings.start_url)))

            # скопируем cookie в requests.Session → экономим авторизацию
            session = requests.Session()
            for c in driver.get_cookies():
                session.cookies.set(c["name"], c["value"])

            # фильтр «გამარჯვებული გამოვლენილია» (победитель определён)
            wait_click(driver, (By.ID, "app_donor_id"))
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, "//option[contains(., 'გამარჯვებული გამოვლენილია')]"))
            )
            wait_click(driver, (By.XPATH, "//option[contains(., 'გამარჯვებული გამოვლენილია')]"))
            wait_click(driver, (By.ID, "search_btn"))
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
            )

            page = 1
            while True:
                logging.info("Page %d", page)
                rows = driver.find_elements(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")

                for idx in tqdm(range(len(rows)), desc=f"Page {page}", unit="tender"):
                    # rows = driver.find_elements(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")
                    if idx >= len(rows):
                        break

                    tender_row = rows[idx]
                    tender_id = tender_row.find_element(By.CSS_SELECTOR, "p strong").text.strip()
                    if tender_id in visited:
                        continue
                    visited.add(tender_id)

                    safe_click(driver, tender_row)
                    # ―――――― Проверка кандидатов на вкладке «შეთავაზებები» ―――――――
                    try:
                        wait_click(driver, (By.XPATH, "//a[contains(., 'შეთავაზებები')]"))
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_all_elements_located(
                                (By.CSS_SELECTOR, "#app_bids table.ktable tbody tr")
                            )
                        )
                        cand_cells: list[WebElement] = driver.find_elements(
                            By.CSS_SELECTOR,
                            "#app_bids table.ktable tbody tr td:nth-child(1)",
                        )
                        candidates: list[str] = [c.text.strip() for c in cand_cells if c.text.strip()]
                        firm_found = any(settings.excluded_firm.lower() in c.lower() for c in candidates)
                        logging.info(
                            "   Найденные кандидаты: %s. Кандидата შპს ,,ინგი-77 %s",
                            ", ".join(candidates) or "—",
                            "найден" if firm_found else "не найдено",
                        )
                        if firm_found:
                            # назад и пропускаем тендер
                            wait_click(driver, (By.ID, "back_button_2"))
                            WebDriverWait(driver, 30).until(
                                EC.presence_of_element_located(
                                    (By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")
                                )
                            )
                            continue
                    except Exception as exc:
                        logging.warning("Не удалось получить список кандидатов (%s) – продолжаем", exc)

                    # «დოკუმენტაცია»
                    WebDriverWait(driver, 30).until(
                        EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'დოკუმენტაცია')]"))
                    )
                    wait_click(driver, (By.XPATH, "//a[contains(., 'დოკუმენტაცია')]"))

                    WebDriverWait(driver, 10).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.answ-file a"))
                    )
                    links = driver.find_elements(By.CSS_SELECTOR, "div.answ-file a")
                    logging.info("  Найдено %d вложений test", len(links))


                    if not memory_manager.check_memory():
                        logging.warning("Memory usage critical, skipping file.")
                        break
                    for link in links:
                        if not memory_manager.check_memory():
                            logging.warning("Memory usage critical, skipping file.")
                            break

                        href = link.get_attribute("href")
                        url = href if href.startswith("http") else f"{root}/{href.lstrip('/')}"

                        display_name = (link.text.strip() or href.split("file=")[-1] or Path(url).name)
                        logging.info("  Скачиваем %s … test test", display_name)

                        for attempt in range(3):
                            try:
                                resp = session.get(url, stream=True, timeout=30)
                                resp.raise_for_status()
                                break
                            except Exception as exc:
                                if attempt == 2:
                                    logging.warning(f"Не скачан {url} после 3 попыток: {exc}")
                                    continue
                                time.sleep(5 * (attempt + 1))

                        cd_name = _filename_from_cd(resp.headers.get("Content-Disposition"))
                        name = cd_name or link.text.strip() or href.split("file=")[-1]
                        if "." not in Path(name).name:
                            name += _ext_from_content_type(resp.headers.get("Content-Type"))

                        out_path = _unique(DOWNLOADS_DIR / _safe_filename(name))

                        with out_path.open("wb") as f:
                            for chunk in resp.iter_content(8192):
                                f.write(chunk)

                        if file_contains_keywords(out_path, settings=settings, memory_manager=None):
                            hits.append(tender_id)
                            break

                    # очистка временных файлов перед следующим тендером
                    shutil.rmtree(DOWNLOADS_DIR)
                    DOWNLOADS_DIR.mkdir(exist_ok=True)
                    memory_manager.force_cleanup()

                    # назад к списку
                    wait_click(driver, (By.ID, "back_button_2"))
                    WebDriverWait(driver, 30).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
                    )

                # --- переход на следующую страницу --------------------------------
                if max_pages and page >= max_pages:
                    break
                try:
                    _next_page(driver)
                    page += 1
                except (TimeoutException, StopIteration):
                    break
        finally:
            if 'driver' in locals():
                driver.quit()

    cache_path.write_text("\n".join(sorted(visited)))
    return hits


if __name__ == "__main__":
    print(scrape_tenders(max_pages=1, headless=False))
