from pathlib import Path
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException, WebDriverException
import platform
import logging



def make_driver(headless: bool = True,
                download_dir: Path | None = None,
                page_load_timeout: int = 60) -> webdriver.Chrome:
    """
    Создаёт экземпляр Chrome-driver, одинаково работающий в Docker (Linux),
    Windows и macOS.

    :param headless:  запускать ли браузер без интерфейса
    :param download_dir: каталог для скачиваемых файлов
    :param page_load_timeout: таймаут загрузки страницы, сек.
    """
    system = platform.system().lower()           # linux / windows / darwin
    opts = webdriver.ChromeOptions()

    # общие предпочтения
    prefs = {
        "download.default_directory": str(download_dir or Path.cwd()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    opts.add_experimental_option("prefs", prefs)
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--disable-infobars")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=ka,en-US")

    # headless-режим (часть опций зависит от ОС)
    if headless:
        opts.add_argument("--headless=new")
        if system == "linux":
            # В Docker эти флаги предотвращают краши Chrome
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
            opts.add_argument("--disable-gpu")

    # выбираем способ, как достать chromedriver
    try:
        if system == "linux":
            # В контейнере chromedriver обычно копируется в / usr / bin
            service = Service("/usr/bin/chromedriver")
        else:
            # На Windows и macOS берём свежий бинарник автоматически
            driver_path = ChromeDriverManager().install()
            service = Service(driver_path)

        driver = webdriver.Chrome(service=service, options=opts)
        driver.set_page_load_timeout(page_load_timeout)
        return driver

    except Exception as exc:                      # pragma: no cover
        logging.critical(f"Failed to start Chrome on {system}: {exc}")
        raise

def wait_click(driver: webdriver.Chrome, locator: tuple[str, str], timeout: int = 20):
    WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator)).click()


def wait_visible(driver: webdriver.Chrome, locator: tuple[str, str], timeout: int = 20):
    return WebDriverWait(driver, timeout).until(EC.visibility_of_element_located(locator))