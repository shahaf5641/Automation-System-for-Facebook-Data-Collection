from __future__ import annotations

import logging
import re
import time
from urllib.parse import parse_qsl, quote_plus, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from selenium.common.exceptions import JavascriptException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

try:
    from .config import Settings
    from .models import PostRecord
except ImportError:  # pragma: no cover
    from config import Settings
    from models import PostRecord

logger = logging.getLogger(__name__)


class GroupUnavailableError(RuntimeError):
    pass


class FacebookScraper:
    def __init__(self, driver: WebDriver, settings: Settings, wait_seconds: int = 10) -> None:
        self.driver = driver
        self.settings = settings
        self.wait_seconds = wait_seconds
        self.stuck_scroll_recovery_seconds = 2.0
        self.stuck_recovery_cooldown_seconds = 8.0
        self.min_stagnant_rounds_for_recovery = 3
        self.max_overlay_recoveries_per_group = 3

    def login(self) -> None:
        self._open_facebook_in_new_tab()
        self._wait_for_page_settle(timeout=3.0)
        if self._is_logged_in_fast():
            logger.info("Already logged in, skipping login process.")
            return
        logger.info("Waiting for manual Facebook login in the opened Chrome window...")
        self._wait_for_manual_login()
        logger.info("Manual login completed.")

    def _open_facebook_in_new_tab(self) -> None:
        # Keep Facebook flow inside a browser tab (not a separate popup flow).
        self.driver.get("about:blank")
        self.driver.execute_script("window.open(arguments[0], '_blank');", "https://www.facebook.com/")
        handles = self.driver.window_handles
        if handles:
            self.driver.switch_to.window(handles[-1])

    def get_group_links(self, desired_count: int) -> list[str]:
        search_url = f"https://www.facebook.com/search/groups/?q={quote_plus(self.settings.search_word)}"
        self.driver.get(search_url)
        self._wait_for_page_settle()
        self._dismiss_cookie_banners()
        self._try_toggle_public_groups()

        group_links: list[str] = []
        seen: set[str] = set()
        stagnant_rounds = 0
        scroll_rounds = 0
        max_scroll_rounds = max(8, desired_count * 2)

        # Collect all group links found on the search page without text-based filtering.
        while len(group_links) < desired_count and stagnant_rounds < 10 and scroll_rounds < max_scroll_rounds:
            current_links = self._extract_group_links_from_page()
            logger.info("Search round found %s group-link candidates.", len(current_links))
            before_count = len(group_links)
            for link in current_links:
                normalized = self._normalize_group_link(link)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                group_links.append(normalized)
                if len(group_links) >= desired_count:
                    break

            stagnant_rounds = 0 if len(group_links) > before_count else stagnant_rounds + 1
            if len(group_links) < desired_count:
                self._scroll_for_more_content(timeout=1.2)
                scroll_rounds += 1

        logger.info("Collected %s group links.", len(group_links))
        return group_links

    def scrape_group_posts(self, group_link: str, group_index: int) -> list[PostRecord]:
        logger.info("[%s/%s] Opening group: %s", group_index, self.settings.group_links_number, group_link)
        self.driver.get(group_link)
        self._wait_for_page_settle()
        self._kickstart_group_scroll()

        records: list[PostRecord] = []
        seen_post_keys: set[str] = set()
        previous_scroll_position = -1
        stagnant_rounds = 0
        last_progress_at = time.monotonic()
        last_recovery_at = 0.0
        overlay_recoveries = 0

        initial_posts = self._wait_for_first_posts(group_link, timeout_seconds=10)
        if self._append_new_posts(initial_posts, seen_post_keys, records, group_index):
            last_progress_at = time.monotonic()

        while len(records) < self.settings.posts_from_each_group and stagnant_rounds < 10:
            if self._recover_from_media_or_overlay(group_link):
                overlay_recoveries += 1
                if overlay_recoveries > self.max_overlay_recoveries_per_group:
                    raise GroupUnavailableError(
                        f"Skipping group after repeated media/overlay redirects: {group_link}"
                    )
                continue

            self._dismiss_interrupting_dialog()
            self._expand_see_more_buttons()

            parsed_posts = self._parse_posts_from_html(group_link)
            new_count = self._append_new_posts(parsed_posts, seen_post_keys, records, group_index)
            if new_count:
                last_progress_at = time.monotonic()
                stagnant_rounds = 0  # FIX: reset immediately when new posts found

            if len(records) >= self.settings.posts_from_each_group:
                break

            current_scroll_position = self._current_scroll_metric()
            now = time.monotonic()
            should_recover = (
                new_count == 0
                and stagnant_rounds >= self.min_stagnant_rounds_for_recovery
                and now - last_progress_at >= self.stuck_scroll_recovery_seconds
                and now - last_recovery_at >= self.stuck_recovery_cooldown_seconds
            )
            if should_recover:
                time.sleep(2.0)
                self._recover_stuck_feed(group_link, aggressive=stagnant_rounds >= 6)
                last_recovery_at = time.monotonic()

            if current_scroll_position == previous_scroll_position and new_count == 0:
                stagnant_rounds += 1
            previous_scroll_position = current_scroll_position

            if len(records) < self.settings.posts_from_each_group and stagnant_rounds < 10:
                self._scroll_for_more_content(timeout=1.2)
                time.sleep(0.3)  # FIX: let FB lazy-load settle

        logger.info("Finished group %s with %s posts.", group_index, len(records))
        return records[: self.settings.posts_from_each_group]

    def _append_new_posts(
        self,
        parsed_posts: list[PostRecord],
        seen_post_keys: set[str],
        records: list[PostRecord],
        group_index: int,
    ) -> int:
        new_count = 0
        for post in parsed_posts:
            normalized_content = re.sub(r"\s+", " ", post.post_content).strip().casefold()
            if not normalized_content:
                continue
            key = post.post_link.strip() if post.post_link else normalized_content
            if key in seen_post_keys:
                continue
            seen_post_keys.add(key)
            records.append(post)
            new_count += 1
            logger.info(
                "Captured post %s/%s from group %s: %s",
                len(records),
                self.settings.posts_from_each_group,
                group_index,
                post.author_name or "Unknown author",
            )
            if len(records) >= self.settings.posts_from_each_group:
                break
        return new_count

    def _wait_for_first_posts(self, group_link: str, timeout_seconds: float) -> list[PostRecord]:
        deadline = time.monotonic() + timeout_seconds
        overlay_recoveries = 0
        attempts = 0
        while time.monotonic() < deadline:
            if self._recover_from_media_or_overlay(group_link):
                overlay_recoveries += 1
                if overlay_recoveries > self.max_overlay_recoveries_per_group:
                    raise GroupUnavailableError(
                        f"Skipping group after repeated media/overlay redirects: {group_link}"
                    )
                continue
            self._dismiss_interrupting_dialog()
            self._expand_see_more_buttons()
            posts = self._parse_posts_from_html(group_link)
            if posts:
                return posts
            attempts += 1
            # Keep pushing the feed down while waiting for first posts.
            self._scroll_for_more_content(timeout=0.9)
            if attempts % 3 == 0:
                self._dismiss_interrupting_dialog()
            self._wait_for_page_settle(timeout=0.4)

        page_text = self._clean_text(self.driver.page_source)
        if self._has_interrupting_group_gate(page_text):
            raise GroupUnavailableError(f"Skipping blocked or non-readable group: {group_link}")
        raise GroupUnavailableError(
            f"Skipping group after failing to extract posts within {int(timeout_seconds)} seconds: {group_link}"
        )

    def _kickstart_group_scroll(self) -> None:
        # Force initial feed movement immediately after opening a group.
        self._dismiss_interrupting_dialog()
        self._wait_for_page_settle(timeout=0.5)
        for _ in range(3):
            self._expand_see_more_buttons()
            moved = self._scroll_feed_step()
            self._wait_for_page_settle(timeout=0.35)
            if moved:
                break

    def _try_toggle_public_groups(self) -> None:
        toggled = False
        try:
            self._wait_for_page_settle(timeout=1.5)
            toggle_targets = self.driver.find_elements(
                By.XPATH,
                (
                    "//*[self::span or self::div][contains(normalize-space(.), 'קבוצות ציבוריות') "
                    "or contains(normalize-space(.), 'Public groups')]"
                ),
            )
            for target in toggle_targets:
                try:
                    switch = target.find_element(
                        By.XPATH,
                        "./ancestor::*[self::div or self::li][1]//*[(@role='switch' or @aria-checked) and not(@disabled)]",
                    )
                except Exception:
                    continue
                state = (switch.get_attribute("aria-checked") or "").lower()
                if state == "true":
                    logger.info("Public groups toggle already enabled.")
                    return
                self._safe_click(switch)
                toggled = True
                break
        except Exception as exc:
            logger.debug("Public groups toggle could not be applied: %s", exc)
        if toggled:
            logger.info("Public groups toggle clicked.")
            self._wait_for_page_settle(timeout=1.0)

    def _extract_group_links_from_page(self) -> list[str]:
        raw_candidates = self.driver.execute_script(
            """
            const anchors = Array.from(document.querySelectorAll("a[href*='/groups/']"));
            return anchors
              .map((a) => (a && a.href ? a.href : ""))
              .filter((href) => !!href);
            """
        )
        candidates: list[str] = []
        for href in raw_candidates or []:
            if isinstance(href, str) and href:
                candidates.append(href)
        return candidates

    def _expand_see_more_buttons(self) -> None:
        self.driver.execute_script(
            """
            const labels = ['see more', 'more', 'עוד', 'ראה עוד', 'הצג עוד'];
            const elements = Array.from(document.querySelectorAll('button, [role="button"]'));
            for (const element of elements) {
              const text = (element.innerText || element.textContent || '').trim().toLowerCase();
              if (!text) continue;
              if (!labels.some((label) => text === label || text.endsWith(label) || text.includes(label + '…') || text.includes(label + '...'))) {
                continue;
              }
              if (element.closest('a[href]')) continue;
              if (element.offsetParent === null) continue;
              try { element.click(); } catch (error) {}
            }
            """
        )

    # ---------------------------------------------------------------------------
    # Core fix: strip the comments subtree from each post node before parsing
    # ---------------------------------------------------------------------------

    def _parse_posts_from_html(self, group_link: str) -> list[PostRecord]:
        soup = BeautifulSoup(self.driver.page_source, "html.parser")
        post_nodes = soup.select("div[role='article']")
        results: list[PostRecord] = []

        for node in post_nodes:
            # FIX: skip nested article nodes — FB renders comments as articles
            # inside the parent post article; we never want those.
            if node.find_parent("div", attrs={"role": "article"}):
                continue

            # FIX: destructively remove the comments subtree from this copy of
            # the node so that commenter names and comment text can never leak
            # into author_name or post_content.
            self._remove_comments_subtree(node)

            post_link, post_time = self._extract_post_link_and_time(node)
            author_name = self._extract_author_name(node)
            if not post_link or not author_name:
                continue

            post_content = self._extract_post_content(node, author_name)
            if not post_content:
                continue
            if not post_time:
                post_time = "Unknown time"

            results.append(
                PostRecord(
                    author_name=author_name,
                    post_content=post_content,
                    post_link=post_link,
                    post_time=post_time,
                    group_link=group_link,
                )
            )

        return results

    def _remove_comments_subtree(self, node: Tag) -> None:
        """
        Destructively strip everything in a post node that belongs to the
        comments / reactions area, working on the BeautifulSoup in-memory copy.

        Strategy (applied in order):
          1. Remove nested <div role="article"> elements (comment cards).
          2. Remove containers whose aria-label mentions "comment/תגובה/תגובות".
          3. Remove reaction/action bar containers (aria-label with like/share/…).
          4. Remove the comment-composer area (contains a "write a comment" input).
        """
        # 1. Nested article elements are always comments/replies
        for nested in node.find_all("div", attrs={"role": "article"}):
            nested.decompose()

        # 2. Comment section containers
        comment_label = re.compile(r"comment|תגובה|תגובות", re.I)
        for tag in node.find_all(attrs={"aria-label": comment_label}):
            tag.decompose()

        # 3. Reaction / action bar
        reaction_label = re.compile(r"reaction|like|share|לייק|שיתוף", re.I)
        for tag in node.find_all(attrs={"aria-label": reaction_label}):
            tag.decompose()

        # 4. Comment composer box — find any ancestor that contains the input
        write_comment = re.compile(r"write a comment|כתיבת תגובה", re.I)
        for tag in node.find_all(
            lambda t: isinstance(t, Tag)
            and (
                t.find(attrs={"placeholder": write_comment})
                or t.find(attrs={"aria-label": write_comment})
            )
        ):
            tag.decompose()

    # ---------------------------------------------------------------------------

    def _extract_author_name(self, node: Tag) -> str:
        candidates: list[str] = []
        for anchor in node.find_all("a", href=True):
            text = self._clean_text(anchor.get_text(" ", strip=True))
            href = anchor.get("href", "")
            if not text or self._looks_like_time_text(text):
                continue
            if "/groups/" in href and "/user/" not in href and "profile.php" not in href:
                continue
            if any(
                noisy in href
                for noisy in ("/posts/", "/permalink/", "/photo", "/photos/", "/watch/", "/videos/", "/reel/")
            ):
                continue
            candidates.append(text)

        for candidate in self._dedupe_chunks(candidates):
            if self._looks_like_author_name(candidate):
                return candidate
        return ""

    def _extract_post_content(self, node: Tag, author_name: str) -> str:
        text_chunks: list[str] = []

        for block in node.select("span[dir='auto'] div[dir='auto'][style*='text-align']"):
            text = self._clean_text(block.get_text(" ", strip=True))
            if text:
                text_chunks.append(text)

        for block in node.select("span[dir='auto'] div[tabindex='-1']"):
            text = self._clean_text(block.get_text(" ", strip=True))
            if text:
                text_chunks.append(text)

        for block in node.select("span[dir='auto'] h3 strong"):
            text = self._clean_text(block.get_text(" ", strip=True))
            if text:
                text_chunks.append(text)

        for block in node.select("div[data-ad-comet-preview='message'] div[dir='auto']"):
            text = self._clean_text(block.get_text(" ", strip=True))
            if text:
                text_chunks.append(text)

        if not text_chunks:
            for block in node.select("div[dir='auto'][style*='text-align']"):
                text = self._clean_text(block.get_text(" ", strip=True))
                if text:
                    text_chunks.append(text)

        deduped_chunks = self._dedupe_chunks(text_chunks)
        combined = self._clean_text(" ".join(deduped_chunks))
        combined = self._strip_repeated_author_prefix(combined, author_name)
        return combined.strip()

    def _extract_post_link_and_time(self, node: Tag) -> tuple[str, str]:
        best_link = ""
        best_time = ""
        for anchor in node.find_all("a", href=True):
            href = anchor.get("href", "")
            text = self._clean_text(anchor.get_text(" ", strip=True))
            label = self._clean_text(anchor.get("aria-label", ""))
            normalized_link = self._normalize_post_link(href)
            candidate_time = self._extract_time_text(text, fallback=label)
            if normalized_link and not best_link:
                best_link = normalized_link
            if candidate_time and not best_time:
                best_time = candidate_time
            if best_link and best_time:
                break
        return best_link, best_time

    def _normalize_group_link(self, url: str) -> str:
        if not url:
            return ""
        absolute_url = urljoin("https://www.facebook.com", url)
        parsed = urlparse(absolute_url)
        path_parts = [part for part in parsed.path.split("/") if part]
        if len(path_parts) < 2 or path_parts[0] != "groups":
            return ""
        # No filtering on found groups: keep any /groups/<slug-or-id> candidate.
        return f"https://www.facebook.com/groups/{path_parts[1]}"

    def _normalize_post_link(self, url: str) -> str:
        if not url:
            return ""
        absolute_url = urljoin("https://www.facebook.com", url)
        parsed = urlparse(absolute_url)
        path_parts = [part for part in parsed.path.split("/") if part]
        query_params = dict(parse_qsl(parsed.query))

        if "story_fbid" in query_params and "id" in query_params:
            return f"https://www.facebook.com/groups/{query_params['id']}/posts/{query_params['story_fbid']}"
        if "multi_permalinks" in query_params:
            value = query_params["multi_permalinks"]
            if path_parts[:1] == ["groups"] and len(path_parts) >= 2:
                return f"https://www.facebook.com/groups/{path_parts[1]}/posts/{value}"
        if path_parts[:2] == ["commerce", "listing"] and len(path_parts) >= 3:
            filtered_query = {}
            if "media_id" in query_params:
                filtered_query["media_id"] = query_params["media_id"]
            query = f"?{urlencode(filtered_query)}" if filtered_query else ""
            return f"https://www.facebook.com/commerce/listing/{path_parts[2]}{query}"
        if path_parts[:1] == ["groups"] and "posts" in path_parts:
            post_index = path_parts.index("posts")
            if len(path_parts) > post_index + 1 and len(path_parts) > 1:
                return f"https://www.facebook.com/groups/{path_parts[1]}/posts/{path_parts[post_index + 1]}"
        if path_parts[:1] == ["groups"] and "permalink" in path_parts:
            group_id = path_parts[1] if len(path_parts) > 1 else ""
            story_id = query_params.get("story_fbid") or query_params.get("multi_permalinks", "")
            if group_id and story_id:
                return f"https://www.facebook.com/groups/{group_id}/posts/{story_id}"
        return ""

    def _dismiss_cookie_banners(self) -> None:
        candidates = [
            (By.XPATH, "//span[normalize-space()='Allow all cookies']/ancestor::div[@role='button'][1]"),
            (By.XPATH, "//span[normalize-space()='Accept all']/ancestor::div[@role='button'][1]"),
            (By.XPATH, "//*[contains(normalize-space(.), 'קובצי Cookie')]/ancestor::div[@role='dialog'][1]//div[@role='button'][1]"),
        ]
        button = self._find_first_visible(candidates, timeout=0, required=False)
        if button is not None:
            self._safe_click(button)

    def _find_first_visible(self, locators, timeout: float | None = None, required: bool = True):
        end_time = time.monotonic() + (timeout if timeout is not None else self.wait_seconds)
        while time.monotonic() <= end_time:
            for by, value in locators:
                elements = self.driver.find_elements(by, value)
                for element in elements:
                    if self._element_is_displayed(element):
                        return element
            time.sleep(0.1)
        if required:
            raise TimeoutException(f"None of the expected elements became visible: {locators}")
        return None

    def _safe_click(self, element) -> None:
        try:
            self.driver.execute_script("arguments[0].click();", element)
            return
        except Exception:
            pass
        try:
            element.click()
        except Exception:
            return

    def _wait_for_page_settle(self, timeout: float = 1.2) -> None:
        end_time = time.monotonic() + timeout
        last_height = -1
        stable_rounds = 0
        while time.monotonic() < end_time:
            try:
                ready_state = self.driver.execute_script("return document.readyState")
                current_height = self.driver.execute_script("return document.body ? document.body.scrollHeight : 0")
            except JavascriptException:
                return
            if ready_state in {"interactive", "complete"} and current_height == last_height:
                stable_rounds += 1
                if stable_rounds >= 2:
                    return
            else:
                stable_rounds = 0
            last_height = current_height
            time.sleep(0.1)

    def _scroll_for_more_content(self, timeout: float = 1.2) -> None:
        if self._scroll_feed_step():
            return
        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            if self._scroll_feed_step():
                return
            time.sleep(0.08)

    def _scroll_feed_step(self) -> bool:
        return bool(
            self.driver.execute_script(
                """
                const scrollBy = Math.max(window.innerHeight * 0.9, 700);
                const beforeWin = Math.round(window.pageYOffset || 0);
                const beforeBody = document.body ? document.body.scrollHeight : 0;

                window.scrollBy(0, scrollBy);

                const afterWin = Math.round(window.pageYOffset || 0);
                const afterBody = document.body ? document.body.scrollHeight : 0;
                if (afterWin > beforeWin || afterBody > beforeBody) {
                  return true;
                }

                const main = document.querySelector("div[role='main']") || document.body;
                const nodes = Array.from(main.querySelectorAll("div, [role='feed'], [role='main']"));
                let target = null;
                let bestRoom = 0;

                for (const el of nodes) {
                  if (!el || el.offsetParent === null) continue;
                  const style = window.getComputedStyle(el);
                  const overflowY = style.overflowY || "";
                  if (!/(auto|scroll)/i.test(overflowY)) continue;
                  const room = (el.scrollHeight || 0) - (el.clientHeight || 0);
                  if (room <= 0) continue;
                  if (room > bestRoom) {
                    bestRoom = room;
                    target = el;
                  }
                }

                if (!target) return false;
                const beforeTop = target.scrollTop || 0;
                target.scrollTop = beforeTop + scrollBy;
                const afterTop = target.scrollTop || 0;
                return afterTop > beforeTop;
                """
            )
        )

    def _current_scroll_metric(self) -> int:
        metric = self.driver.execute_script(
            """
            const win = Math.round(window.pageYOffset || 0);
            const main = document.querySelector("div[role='main']") || document.body;
            const nodes = Array.from(main.querySelectorAll("div, [role='feed'], [role='main']"));
            let best = 0;
            for (const el of nodes) {
              if (!el || el.offsetParent === null) continue;
              const room = (el.scrollHeight || 0) - (el.clientHeight || 0);
              if (room <= 0) continue;
              if ((el.scrollTop || 0) > best) best = Math.round(el.scrollTop || 0);
            }
            return Math.max(win, best);
            """
        )
        try:
            return int(metric or 0)
        except Exception:
            return 0

    def _recover_stuck_feed(self, group_link: str, aggressive: bool = False) -> None:
        self._dismiss_interrupting_dialog()
        if self._recover_from_media_or_overlay(group_link):
            return
        if aggressive:
            up_distance = "Math.max(window.innerHeight * 2.2, 1400)"
            self.driver.execute_script(f"window.scrollBy(0, -({up_distance}));")
            self._wait_for_page_settle(timeout=0.7)
            time.sleep(0.3)
        self.driver.execute_script("window.scrollBy(0, Math.max(window.innerHeight * 0.8, 650));")
        self._wait_for_page_settle(timeout=0.9)

    def _recover_from_media_or_overlay(self, group_link: str) -> bool:
        current_url = self.driver.current_url.casefold()
        if any(fragment in current_url for fragment in ("/photo/", "/photos/", "/video", "/videos/", "/watch/", "/reel/")):
            logger.info("Detected media/overlay view. Returning to group feed.")
            try:
                self.driver.back()
                self._wait_for_page_settle(timeout=0.8)
            except Exception:
                self.driver.get(group_link)
                self._wait_for_page_settle(timeout=1.2)
            return True
        return self._dismiss_interrupting_dialog()

    def _dismiss_interrupting_dialog(self) -> bool:
        buttons = self.driver.find_elements(
            By.XPATH,
            (
                "//div[@role='dialog']//*[self::div or self::span]["
                "normalize-space()='Close' or normalize-space()='Not now' or normalize-space()='סגור' "
                "or normalize-space()='לא עכשיו']/ancestor::*[@role='button'][1]"
            ),
        )
        for button in buttons:
            if self._element_is_displayed(button):
                self._safe_click(button)
                self._wait_for_page_settle(timeout=0.4)
                return True
        return False

    def _clean_text(self, value: str) -> str:
        cleaned = re.sub(r"[\u200e\u200f\u202a-\u202e]", " ", value or "")
        cleaned = cleaned.replace("\xa0", " ")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip(" .\n\t")

    def _dedupe_chunks(self, chunks: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for chunk in chunks:
            normalized = self._clean_text(chunk).casefold()
            if not normalized or normalized in seen:
                continue
            if result and (normalized in result[-1].casefold() or result[-1].casefold() in normalized):
                if len(normalized) <= len(result[-1]):
                    continue
                result.pop()
            seen.add(normalized)
            result.append(self._clean_text(chunk))
        return result

    def _strip_repeated_author_prefix(self, text: str, author_name: str) -> str:
        if not text or not author_name:
            return text
        repeated_prefix = r"^(?:" + re.escape(author_name) + r"\s*){2,}"
        return re.sub(repeated_prefix, author_name + " ", text, flags=re.IGNORECASE).strip()

    def _looks_like_author_name(self, text: str) -> bool:
        parts = [part for part in text.split() if part]
        if not 1 <= len(parts) <= 5:
            return False
        if any(char.isdigit() for char in text):
            return False
        if any(self._looks_like_time_text(token) for token in parts):
            return False
        return all(len(token) <= 30 for token in parts)

    def _extract_time_text(self, text: str, fallback: str = "") -> str:
        candidates = [self._clean_text(text), self._clean_text(fallback)]
        for candidate in candidates:
            if self._looks_like_time_text(candidate):
                return candidate
        return ""

    def _looks_like_time_text(self, text: str) -> bool:
        patterns = [
            r"^\d+\s*(?:m|min|mins|h|hr|hrs|d|day|days|w|week|weeks|mo|month|months|yr|year|years)$",
            r"^(?:just now|now|yesterday)$",
            r"^(?:לפני\s*)?\d+\s*(?:דק(?:ות)?|שעה|שעות|יום|ימים|שבוע|שבועות|חודש|חודשים|שנה|שנים)$",
            r"^\d+\s*(?:דק(?:ות)?|שעה|שעות|יום|ימים|שבוע|שבועות|חודש|חודשים|שנה|שנים)$",
            r"^(?:אתמול|עכשיו)$",
        ]
        normalized = text.casefold().strip()
        return any(re.match(pattern, normalized) for pattern in patterns) or "ago" in normalized.split()

    def _has_interrupting_group_gate(self, page_text: str) -> bool:
        blocking_phrases = [
            "join group", "request to join", "welcome to the group", "private group",
            "content isn't available right now", "הצטרפות לקבוצה", "בקשת הצטרפות",
            "ברוכים הבאים לקבוצה", "קבוצה פרטית", "התוכן אינו זמין כרגע",
        ]
        normalized = page_text.casefold()
        return any(phrase in normalized for phrase in blocking_phrases)

    def _is_logged_in(self) -> bool:
        current_url = self.driver.current_url.casefold()
        if any(fragment in current_url for fragment in ("/login", "/checkpoint", "/recover")):
            return False
        login_fields = self.driver.find_elements(By.CSS_SELECTOR, "input[name='email'], input[name='pass']")
        if any(self._element_is_displayed(field) for field in login_fields):
            return False
        page_text = self.driver.execute_script("return document.body ? document.body.innerText : '';") or ""
        normalized = page_text.casefold()
        if self._has_login_gate_prompt(normalized):
            return False
        return self._has_logged_in_indicators()

    def _element_is_displayed(self, element) -> bool:
        try:
            return element.is_displayed()
        except StaleElementReferenceException:
            return False

    def _wait_for_manual_login(self) -> None:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if self._is_logged_in():
                return
            time.sleep(0.25)
        raise TimeoutException("Timed out waiting for manual Facebook login.")

    def _is_logged_in_fast(self) -> bool:
        current_url = self.driver.current_url.casefold()
        if any(fragment in current_url for fragment in ("/login", "/checkpoint", "/recover")):
            return False
        login_fields = self.driver.find_elements(By.CSS_SELECTOR, "input[name='email'], input[name='pass']")
        if any(self._element_is_displayed(field) for field in login_fields):
            return False
        page_text = self.driver.execute_script("return document.body ? document.body.innerText : '';") or ""
        normalized = page_text.casefold()
        if self._has_login_gate_prompt(normalized):
            return False
        return self._has_logged_in_indicators()

    def _has_logged_in_indicators(self) -> bool:
        logged_in_locators = [
            (By.CSS_SELECTOR, "div[role='feed']"),
            (By.XPATH, "//a[contains(@href, '/groups/feed/')]"),
            (By.XPATH, "//a[contains(@href, '/friends/')]"),
            (By.XPATH, "//a[contains(@href, '/home.php')]"),
            (By.XPATH, "//a[contains(@href, '/marketplace/')]"),
        ]
        for by, value in logged_in_locators:
            for element in self.driver.find_elements(by, value):
                if self._element_is_displayed(element):
                    return True
        return False

    def _has_login_gate_prompt(self, normalized_text: str) -> bool:
        markers = [
            "continue as",
            "use another profile",
            "use another account",
            "create new account",
            "log into another account",
            "log in",
            "login",
            "forgot password",
            "\u05d4\u05de\u05e9\u05da",
            "\u05e9\u05d9\u05de\u05d5\u05e9 \u05d1\u05e4\u05e8\u05d5\u05e4\u05d9\u05dc \u05d0\u05d7\u05e8",
            "\u05e6\u05d5\u05e8 \u05d7\u05e9\u05d1\u05d5\u05df \u05d7\u05d3\u05e9",
            "\u05d4\u05ea\u05d7\u05d1\u05e8",
            "\u05d4\u05ea\u05d7\u05d1\u05e8\u05d5\u05ea",
            "\u05e9\u05db\u05d7\u05ea \u05d0\u05ea \u05d4\u05e1\u05d9\u05e1\u05de\u05d4",
        ]
        return any(marker in normalized_text for marker in markers)

class _PublicGroupsToggleFacebookScraper(FacebookScraper):
    def _try_toggle_public_groups(self) -> None:
        try:
            self._wait_for_page_settle(timeout=1.5)
            status = self.driver.execute_script(
                """
                const normalize = (s) => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
                const targets = ['public groups', '\\u05e7\\u05d1\\u05d5\\u05e6\\u05d5\\u05ea \\u05e6\\u05d9\\u05d1\\u05d5\\u05e8\\u05d9\\u05d5\\u05ea'];
                const blocked = ['nearby', '\\u05d1\\u05e7\\u05e8\\u05d1\\u05ea\\u05d9'];
                const isVisible = (el) => !!el && el.offsetParent !== null;
                const hasTarget = (t) => targets.some((x) => t.includes(x));
                const hasBlocked = (t) => blocked.some((x) => t.includes(x));

                const candidates = Array.from(document.querySelectorAll("button, [role='button'], [role='switch'], [aria-checked], [aria-pressed]"));
                for (const el of candidates) {
                  if (!isVisible(el)) continue;
                  const text = normalize(el.innerText || el.textContent || el.getAttribute('aria-label') || '');
                  if (!text || !hasTarget(text) || hasBlocked(text)) continue;
                  const state = normalize(el.getAttribute('aria-checked') || el.getAttribute('aria-pressed') || '');
                  if (state === 'true') return 'already';
                  try { el.click(); return 'clicked'; } catch (error) {}
                }

                const rows = Array.from(document.querySelectorAll("div, li"));
                for (const row of rows) {
                  if (!isVisible(row)) continue;
                  const rowText = normalize(row.innerText || row.textContent || '');
                  if (!rowText || !hasTarget(rowText) || hasBlocked(rowText)) continue;
                  const switchEl = row.querySelector("[role='switch'], [aria-checked], [aria-pressed], button, [role='button']");
                  if (!switchEl || !isVisible(switchEl)) continue;
                  const state = normalize(switchEl.getAttribute('aria-checked') || switchEl.getAttribute('aria-pressed') || '');
                  if (state === 'true') return 'already';
                  try { switchEl.click(); return 'clicked'; } catch (error) {}
                }
                return 'not_found';
                """
            )
            if status == "already":
                logger.info("Public groups toggle already enabled.")
                return
            if status == "clicked":
                logger.info("Public groups toggle clicked.")
                self._wait_for_page_settle(timeout=1.0)
                return

            # Fallback: old DOM variants with explicit switches
            rows = self.driver.find_elements(
                By.XPATH,
                "//*[@role='switch' or @aria-checked or @aria-pressed]/ancestor::*[self::div or self::li][1]",
            )
            for row in rows:
                row_text = self._clean_text(row.text).casefold()
                if "public groups" not in row_text and "\u05e7\u05d1\u05d5\u05e6\u05d5\u05ea \u05e6\u05d9\u05d1\u05d5\u05e8\u05d9\u05d5\u05ea" not in row_text:
                    continue
                try:
                    switch = row.find_element(By.XPATH, ".//*[@role='switch' or @aria-checked or @aria-pressed]")
                except Exception:
                    continue
                state = (switch.get_attribute("aria-checked") or switch.get_attribute("aria-pressed") or "").lower()
                if state == "true":
                    logger.info("Public groups toggle already enabled.")
                    return
                self._safe_click(switch)
                logger.info("Public groups toggle clicked.")
                self._wait_for_page_settle(timeout=1.0)
                return
        except Exception as exc:
            logger.debug("Public groups toggle could not be applied: %s", exc)


FacebookScraper = _PublicGroupsToggleFacebookScraper
