import logging
import json
import shutil
import time
from pathlib import Path
import re
import tempfile
from typing import Set, List
from urllib.parse import unquote, urlparse
import mimetypes
import requests

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tqdm import tqdm

from .config import START_URL
from .driver_utils import make_driver, wait_click
from .extractor import file_contains_keywords


# ---------- вспомогательные утилиты ---------------------------------------- #
_CD_FILENAME_RX = re.compile(
    r"""filename\*?            # filename или filename*
        (?:=[^']*'')?          # =utf-8''  (может отсутствовать)
        ["']?                  # открывающая кавычка
        (?P<name>[^";]+)       # само имя
    """,
    re.I | re.X,
)


def _filename_from_cd(cd: str | None) -> str | None:
    """Парсим Content-Disposition → имя файла (или None)."""
    if not cd:
        return None
    m = _CD_FILENAME_RX.search(cd)
    if m:
        return unquote(m["name"].strip())
    return None


# База соответствий, если mimetypes не знает расширение
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
    ct = ct.split(";")[0].strip()
    ext = mimetypes.guess_extension(ct) or _CT_EXT_MAP.get(ct, "")
    return ext or ""


# ---------- основной скрейпер ---------------------------------------------- #
def scrape_tenders(max_pages: int | None = None, headless: bool = True) -> List[str]:
    DOWNLOADS_DIR = Path("downloads")
    if DOWNLOADS_DIR.exists():
        shutil.rmtree(DOWNLOADS_DIR)
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    cache_path = Path("visited_ids.txt")
    visited: Set[str] = set(cache_path.read_text().split()) if cache_path.exists() else set()
    hits: List[str] = []

    with tempfile.TemporaryDirectory() as tmpdir:
<<<<<<< HEAD
        driver = make_driver(headless=headless, download_dir=Path(tmpdir))
        driver.get(START_URL)

        # корень без /public
        root = "{uri.scheme}://{uri.netloc}".format(uri=urlparse(START_URL))

        # сессия c куками браузера
        session = requests.Session()
        for c in driver.get_cookies():
            session.cookies.set(c["name"], c["value"])

        # фильтры
=======
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
>>>>>>> 6d821913ee3c7a33361b5dcb99e1b015e65f990b
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
<<<<<<< HEAD
=======
                # ре-получаем список
>>>>>>> 6d821913ee3c7a33361b5dcb99e1b015e65f990b
                rows = driver.find_elements(By.CSS_SELECTOR, "#list_apps_by_subject tbody tr")
                if i >= len(rows):
                    break

                tender = rows[i]
                tender_id = tender.find_element(By.CSS_SELECTOR, "p strong").text.strip()
                if tender_id in visited:
                    continue
                visited.add(tender_id)

<<<<<<< HEAD
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", tender)
                try:
                    tender.click()
                except Exception:
                    ActionChains(driver).move_to_element(tender).click().perform()

=======
                # безопасный клик по тендеру
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", tender)
                try:
                    tender.click()
                except:
                    ActionChains(driver).move_to_element(tender).click().perform()

                # ждём вкладку "დოკუმენტაცია"
>>>>>>> 6d821913ee3c7a33361b5dcb99e1b015e65f990b
                WebDriverWait(driver, 30).until(
                    EC.element_to_be_clickable((By.XPATH, "//a[contains(., 'დოკუმენტაცია')]"))
                )
                wait_click(driver, (By.XPATH, "//a[contains(., 'დოკუმენტაცია')]"))

<<<<<<< HEAD
=======
                # ждём, пока появятся ссылки на файлы
>>>>>>> 6d821913ee3c7a33361b5dcb99e1b015e65f990b
                WebDriverWait(driver, 10).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.answ-file a"))
                )

<<<<<<< HEAD
                files = driver.find_elements(By.CSS_SELECTOR, "div.answ-file a")
                logging.info("→ найдено %d ссылок на документы", len(files))

                for link in files:
                    href = link.get_attribute("href")
                    file_url = href if href.startswith("http") else f"{root}/{href.lstrip('/')}"
=======
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
>>>>>>> 6d821913ee3c7a33361b5dcb99e1b015e65f990b

                    logging.info("   → скачиваем файл: %s", file_url)
                    try:
                        r = session.get(file_url, stream=True, timeout=60)
<<<<<<< HEAD
=======
                        logging.debug(" → Response headers: %s", r.headers)
>>>>>>> 6d821913ee3c7a33361b5dcb99e1b015e65f990b
                        r.raise_for_status()
                    except Exception as e:
                        logging.warning("Не удалось скачать %s: %s", file_url, e)
                        continue

<<<<<<< HEAD
                    # --------- определяем понятное имя файла -----------
                    cd_fname = _filename_from_cd(r.headers.get("Content-Disposition"))
                    link_text = link.text.strip()
                    raw_id = href.split("file=")[-1].split("&")[0]
                    name = cd_fname or link_text or raw_id

                    # расширение
                    if "." not in Path(name).name:
                        name += _ext_from_content_type(r.headers.get("Content-Type"))

                    out_path = DOWNLOADS_DIR / name
                    with open(out_path, "wb") as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)

                # проверяем скачанные файлы
                for dl in DOWNLOADS_DIR.iterdir():
=======
                    filename = href.split("file=")[-1].split("&")[0]
                    out_path = DOWNLOADS_DIR  / filename
                    with open(out_path, "wb") as f:
                        for chunk in r.iter_content(1024):
                            f.write(chunk)

                # проверяем скачанные
                for dl in Path(tmpdir).iterdir():
>>>>>>> 6d821913ee3c7a33361b5dcb99e1b015e65f990b
                    if file_contains_keywords(dl):
                        hits.append(tender_id)
                        logging.info("+++ тендер %s содержит ключи", tender_id)
                        break

<<<<<<< HEAD
                # назад
=======
                # возвращаемся назад
>>>>>>> 6d821913ee3c7a33361b5dcb99e1b015e65f990b
                wait_click(driver, (By.ID, "back_button_2"))
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
                )
                time.sleep(0.5)

<<<<<<< HEAD
=======
            # листаем страницу
>>>>>>> 6d821913ee3c7a33361b5dcb99e1b015e65f990b
            if max_pages and page_num >= max_pages:
                break
            try:
                wait_click(driver, (By.ID, "btn_next"))
                page_num += 1
                WebDriverWait(driver, 30).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "#list_apps_by_subject tbody tr"))
                )
<<<<<<< HEAD
            except Exception:
=======
            except:
>>>>>>> 6d821913ee3c7a33361b5dcb99e1b015e65f990b
                break

        driver.quit()

    cache_path.write_text("\n".join(sorted(visited)))
<<<<<<< HEAD
    return hits
=======
    return hits
>>>>>>> 6d821913ee3c7a33361b5dcb99e1b015e65f990b
