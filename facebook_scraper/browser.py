from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

logger = logging.getLogger(__name__)


def build_driver(headless: bool = True, profile_dir: str = ".chrome-profile") -> webdriver.Chrome:
    chrome_options = Options()
    profile_path = Path(profile_dir).resolve()
    profile_path.mkdir(parents=True, exist_ok=True)
    _seed_profile_from_installed_chrome(profile_path)

    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument("--disable-usb-keyboard-detect")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--silent")
    chrome_options.add_argument("--start-minimized")
    chrome_options.add_argument("--lang=he-IL")
    chrome_options.add_argument("--window-size=1600,1000")
    chrome_options.add_argument(f"--user-data-dir={profile_path}")
    chrome_options.add_argument("--profile-directory=Default")
    chrome_options.page_load_strategy = "eager"
    chrome_options.add_experimental_option(
        "prefs",
        {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "autofill.profile_enabled": False,
            "autofill.credit_card_enabled": False,
        },
    )
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    chrome_options.add_experimental_option("useAutomationExtension", False)

    if headless:
        chrome_options.add_argument("--headless=new")

    logger.info("Starting Chrome driver...")
    logger.info("Using Chrome profile directory: %s", profile_path)
    # Selenium Manager (bundled with modern Selenium) resolves the driver automatically.
    service = Service(log_output=os.devnull)
    driver = webdriver.Chrome(options=chrome_options, service=service)
    try:
        driver.minimize_window()
    except Exception:
        pass
    return driver


def _seed_profile_from_installed_chrome(profile_path: Path) -> None:
    default_profile = profile_path / "Default"
    if default_profile.exists() and any(default_profile.iterdir()):
        return

    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if not local_app_data:
        return

    source_user_data = Path(local_app_data) / "Google" / "Chrome" / "User Data"
    source_default = source_user_data / "Default"
    if not source_default.exists():
        return

    logger.info("Seeding automation profile from installed Chrome profile.")
    try:
        shutil.copy2(source_user_data / "Local State", profile_path / "Local State")
    except Exception as exc:
        logger.warning("Could not copy Chrome Local State file: %s", exc)
    _copy_profile_tree(source_default, default_profile)


def _copy_profile_tree(source: Path, destination: Path) -> None:
    excluded_names = {
        "Cache",
        "Code Cache",
        "Crashpad",
        "GPUCache",
        "GrShaderCache",
        "ShaderCache",
        "Service Worker",
        "Session Storage",
        "Sessions",
        "Extension Rules",
        "Extension Scripts",
        "Extension State",
        "Blob Storage",
        "DawnCache",
    }
    excluded_suffixes = {".lock", ".tmp"}
    ignored_exact_names = {"LOCK", "SingletonCookie", "SingletonLock", "SingletonSocket"}

    destination.mkdir(parents=True, exist_ok=True)

    for root, dirs, files in os.walk(source):
        src_root = Path(root)
        rel_root = src_root.relative_to(source)
        dst_root = destination / rel_root
        dst_root.mkdir(parents=True, exist_ok=True)

        dirs[:] = [d for d in dirs if d not in excluded_names and d not in ignored_exact_names]

        for file_name in files:
            if file_name in ignored_exact_names:
                continue
            if any(file_name.endswith(suffix) for suffix in excluded_suffixes):
                continue
            src_file = src_root / file_name
            dst_file = dst_root / file_name
            try:
                shutil.copy2(src_file, dst_file)
            except PermissionError:
                logger.debug("Skipping locked Chrome file: %s", src_file)
            except OSError:
                logger.debug("Skipping unavailable Chrome file: %s", src_file)
