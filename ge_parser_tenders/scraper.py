import logging
import shutil
import json
import time
from pathlib import Path
import tempfile
from typing import Set, List
import requests
from urllib.parse import urlparse
from .config import START_URL
from .driver_utils import make_driver, wait_click
from .extractor import file_contains_keywords
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from tqdm import tqdm

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