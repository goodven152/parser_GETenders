"""
scraper.py ― грузинские тендеры
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* проходит по страницам сайта, кликает «დოკუმენტაცია»
* скачивает все прикреплённые файлы
* даёт им читаемые ASCII-имена (slug-ified), чтобы внешние CLI-утилиты
  вроде *pdftotext* не спотыкались о юникод-пути
* ищет в документах ключевые слова и сохраняет ID тендера,
  если хотя бы один файл «срабатывает»

"""

from __future__ import annotations

import logging
import mimetypes
import shutil
import tempfile
import time
import re
from pathlib import Path
from typing import List, Set
from urllib.parse import unquote, urlparse

import requests
from slugify import slugify
from tqdm import tqdm
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from .config import START_URL
from .driver_utils import make_driver, wait_click
from .extractor import file_contains_keywords

# --------------------------------------------------------------------------- #
#                               helpers                                       #
# --------------------------------------------------------------------------- #

# ── имя из Content-Disposition ───────────────────────────────────────────────
_CD_FILENAME_RX = re.compile(
    r"""filename\*?          # filename или filename*
        (?:=[^']*'')?        # =utf-8''  (может отсутствовать)
        ["']?                # возможная кавычка
        (?P<name>[^";]+)     # собственно имя
    """,
    re.I | re.X,
)


def _decode_maybe_utf8(s: str) -> str:
    """
    Сервер прислал UTF-8, но заголовок трекнулся как Latin-1.
    Пример: '=áá…'  →  'დანართი …'
    """
    try:
        return s.encode("latin1").decode("utf-8")
    except UnicodeDecodeError:
        return s


def _filename_from_cd(cd: str | None) -> str | None:
    if not cd:
        return None

    # RFC 5987 ―  filename*=utf-8''%E1%83%93%E1%83%90…
    if "filename*" in cd:
        _, value = cd.split("filename*", 1)[1].split("=", 1)
        if "''" in value:
            enc, _, raw = value.partition("''")
            return unquote(raw, encoding=enc, errors="replace")

    # filename="დანართი.pdf"  (может быть уже «битым» UTF-8)
    m = _CD_FILENAME_RX.search(cd)
    if m:
        name = m["name"].strip().strip('"')
        return _decode_maybe_utf8(name)

    return None


# ── расширение по Content-Type ───────────────────────────────────────────────
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


# ── безопасное ASCII-имя + уникальность ─────────────────────────────────────
def _safe_filename(raw: str, ext_hint: str = "") -> str:
    """
    Возвращает «ASCII-дружественное» имя:
      • slugify → латиница/цифры/_
      • пробелы → _
      • если slug пустой, кладём «file»
    """
    stem, ext = Path(raw).stem, Path(raw).suffix or ext_hint
    slug = slugify(stem, lowercase=False, separator="_")
    if not slug:
        slug = "file"
    return f"{slug}{ext}"


def _unique(path: Path) -> Path:
    """file.pdf → file_1.pdf, file_2.pdf … если уже существует"""
    if not path.exists():
        return path
    stem, ext = path.stem, path.suffix
    idx = 1
    while True:
        candidate = path.with_name(f"{stem}_{idx}{ext}")
        if not candidate.exists():
            return candidate
        idx += 1


# --------------------------------------------------------------------------- #
#                               main scraper                                  #
# --------------------------------------------------------------------------- #
def scrape_tenders(max_pages: int | None = None, *, headless: bool = True) -> List[str]:
    """
    Возвращает список ID тендеров, в чьих документах найдены ключевые слова.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    DOWNLOADS_DIR = Path("downloads")
    if DOWNLOADS_DIR.exists():
        shutil.rmtree(DOWNLOADS_DIR)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    cache_path = Path("visited_ids.txt")
    visited: Set[str] = set(cache_path.read_text().split()) if cache_path.exists() else set()
    hits: List[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        # браузер
        driver = make_driver(headless=headless, download_dir=Path(tmpdir))
        driver.get(START_URL)

        root = "{uri.scheme}://{uri.netloc}".format(uri=urlparse(START_URL))

        # сессия с cookie браузера
        session = requests.Session()
        for c in driver.get_cookies():
            session.cookies.set(c["name"], c["value"])

        # фильтр «გამარჯვებული გამოვლენილია» (= победитель определён)
        wait_click(driver, (By.ID, "app_donor_id"))
        time.sleep(2)
        wait_click(driver, (By.XPATH, "//option[contains(., 'გამარჯვებული გამოვლენილია')]"))
        time.sleep(1)
        wait_click(driver, (By.ID, "search_btn"))
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
        )

        page = 1
        while True:
            logging.info("Page %d", page)
            rows = driver.find_elements(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")

            for idx in tqdm(range(len(rows)), desc=f"Page {page}", unit="tender"):
                rows = driver.find_elements(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")
                if idx >= len(rows):
                    break

                tender_row = rows[idx]
                tender_id = tender_row.find_element(By.CSS_SELECTOR, "p strong").text.strip()
                if tender_id in visited:
                    continue
                visited.add(tender_id)

                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", tender_row)
                try:
                    tender_row.click()
                except Exception:
                    ActionChains(driver).move_to_element(tender_row).click().perform()

                # ссылка «დოკუმენტაცია»
                WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'დოკუმენტაცია')]"))
                )
                wait_click(driver, (By.XPATH, "//a[contains(., 'დოკუმენტაცია')]"))

                WebDriverWait(driver, 10).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.answ-file a"))
                )
                links = driver.find_elements(By.CSS_SELECTOR, "div.answ-file a")
                logging.info("  ↳ найдено %d вложений", len(links))

                for link in links:
                    href = link.get_attribute("href")
                    url = href if href.startswith("http") else f"{root}/{href.lstrip('/')}"

                    try:
                        resp = session.get(url, stream=True, timeout=60)
                        resp.raise_for_status()
                    except Exception as exc:
                        logging.warning("    ⚠ не скачан %s (%s)", url, exc)
                        continue

                    # имя + расширение
                    cd_name = _filename_from_cd(resp.headers.get("Content-Disposition"))
                    name = cd_name or link.text.strip() or href.split("file=")[-1]
                    if "." not in Path(name).name:
                        name += _ext_from_content_type(resp.headers.get("Content-Type"))

                    safe_name = _safe_filename(name)
                    out_path = _unique(DOWNLOADS_DIR / safe_name)

                    with out_path.open("wb") as f:
                        for chunk in resp.iter_content(8192):
                            f.write(chunk)
                    new_files = list(DOWNLOADS_DIR.iterdir())  # snapshot до очистки
                    for fpath in new_files:
                        if file_contains_keywords(fpath):
                            hits.append(tender_id)
                            break
                    shutil.rmtree(DOWNLOADS_DIR)            # подчистили
                    DOWNLOADS_DIR.mkdir(exist_ok=True)


                # проверяем скачанные
                for fpath in DOWNLOADS_DIR.iterdir():
                    if file_contains_keywords(fpath):
                        logging.info("  ✅ тендер %s содержит ключи", tender_id)
                        hits.append(tender_id)
                        break

                # назад к списку
                wait_click(driver, (By.ID, "back_button_2"))
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
                )

            if max_pages and page >= max_pages:
                break
            try:
                wait_click(driver, (By.ID, "btn_next"))
                page += 1
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
                )
            except Exception:
                break

        driver.quit()

    cache_path.write_text("\n".join(sorted(visited)))
    return hits


if __name__ == "__main__":
    # пример запуска: python scraper.py  -- отладка без CLI-обёртки
    print(scrape_tenders(max_pages=1, headless=False))
