from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path

import pandas as pd

from .browser import build_driver
from .config import Settings
from .scraper import FacebookScraper, GroupUnavailableError


class QueueLogHandler(logging.Handler):
    def __init__(self, log_queue: queue.Queue[str]) -> None:
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith("facebook_scraper"):
            return
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            self.handleError(record)


class DriverControl:
    def __init__(self) -> None:
        self._driver = None
        self._lock = threading.Lock()
        self.stop_requested = False

    def attach_driver(self, driver) -> None:
        with self._lock:
            self._driver = driver

    def clear_driver(self) -> None:
        with self._lock:
            self._driver = None

    def request_stop(self) -> None:
        self.stop_requested = True
        with self._lock:
            driver = self._driver
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


def configure_logging(extra_handlers: list[logging.Handler] | None = None) -> None:
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    for handler in extra_handlers or []:
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("selenium").setLevel(logging.ERROR)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    logging.getLogger("WDM").setLevel(logging.ERROR)
    logging.getLogger("webdriver_manager").setLevel(logging.ERROR)


def run_scraper(settings: Settings, control: DriverControl | None = None) -> int:
    logger = logging.getLogger("facebook_scraper")
    if control and control.stop_requested:
        logger.warning("Run was cancelled before start.")
        return 2

    driver = None

    try:
        driver = build_driver(headless=settings.headless, profile_dir=settings.chrome_profile_dir)
        if control:
            control.attach_driver(driver)

        scraper = FacebookScraper(driver=driver, settings=settings)
        scraper.login()
        if control and control.stop_requested:
            logger.warning("Run stopped by user.")
            return 2

        desired_groups = settings.group_links_number
        posts_per_group = settings.posts_from_each_group
        target_total_posts = desired_groups * posts_per_group

        # Collect 3x groups as backup so stuck/empty groups can be replaced.
        candidate_groups = max(desired_groups * 3, desired_groups + 2)
        group_links = scraper.get_group_links(desired_count=candidate_groups)
        if control and control.stop_requested:
            logger.warning("Run stopped by user.")
            return 2

        if not group_links:
            logger.error("No group links were collected. The selectors may need an update.")
            return 1

        all_records = []
        contributing_groups = 0
        for group_idx, group_link in enumerate(group_links, start=1):
            if control and control.stop_requested:
                logger.warning("Run stopped by user.")
                return 2
            if len(all_records) >= target_total_posts:
                break
            try:
                records = scraper.scrape_group_posts(group_link=group_link, group_index=group_idx)
            except GroupUnavailableError as exc:
                logger.warning("%s", exc)
                continue

            if records:
                contributing_groups += 1
                remaining_posts = target_total_posts - len(all_records)
                all_records.extend(records[:remaining_posts])

        if len(all_records) < target_total_posts:
            logger.warning(
                "Only %s/%s posts were collected. Try a broader search term.",
                len(all_records),
                target_total_posts,
            )
        elif contributing_groups > desired_groups:
            logger.info(
                "Completed target posts by using %s groups (requested groups: %s).",
                contributing_groups,
                desired_groups,
            )

        df = pd.DataFrame(
            [
                {
                    "Author": record.author_name,
                    "Post Time": record.post_time,
                    "Content": record.post_content,
                    "Post Link": record.post_link,
                }
                for record in all_records
            ]
        )
        df.reset_index(drop=True, inplace=True)

        output_path = Path(settings.output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        logger.info("Done. Saved %s records to %s", len(df), output_path.resolve())
        logger.info("Expected table size based on settings: %s", settings.expected_table_size)
        return 0
    except Exception as exc:
        if control and control.stop_requested:
            logger.warning("Run stopped by user.")
            return 2
        logger.exception("Unexpected error during run: %s", exc)
        return 1
    finally:
        if control:
            control.clear_driver()
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass
