"""Weibo text collector adapted from weibo-crawler.

Fetches weibo posts (text only) for specified user IDs.
Requires valid cookie for authenticated access.
"""

import logging
import os
import random
import re
import time
from datetime import datetime, timedelta

import requests
from lxml import etree
from requests.adapters import HTTPAdapter

from tools.config_manager import IdolConfig
from tools.persistence import clear_resume_meta, load_json_list, load_resume_meta, safe_json_save, save_resume_meta

logger = logging.getLogger(__name__)

DTFORMAT = "%Y-%m-%dT%H:%M:%S"


class WeiboCollector:
    """Collects weibo post texts for given user IDs."""

    def __init__(self, config: IdolConfig):
        self.config = config
        self.session = requests.Session()
        adapter = HTTPAdapter(max_retries=3)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.headers = {
            "Referer": "https://m.weibo.cn/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": random.choice(config.anti_ban.user_agents),
        }

        # Cookie setup: try to load from env/config, but don't fail here
        self._cookie_ready = False
        cookie = config.get_cookie()
        if cookie:
            self._setup_cookie(cookie)
            self._validate_cookie()
            self._cookie_ready = True

        # Stats tracking
        self.request_count = 0
        self.api_errors = 0
        self.start_time = None

    @property
    def has_cookie(self) -> bool:
        """Check if a valid cookie has been set."""
        return self._cookie_ready

    def set_cookie(self, cookie_string: str):
        """Set cookie after initialization. Validates immediately."""
        self._setup_cookie(cookie_string)
        self._validate_cookie()
        self._cookie_ready = True

    def _ensure_cookie(self):
        """Raise if cookie is not set. Call before any API request."""
        if not self._cookie_ready:
            raise ValueError(
                "Weibo cookie not set. Call set_cookie() first or set WEIBO_COOKIE env var."
            )

    def _setup_cookie(self, cookie_string: str):
        """Parse and set cookie on session."""
        core_cookies = {}
        match_sub = re.search(r"SUB=(.*?)(;|$)", cookie_string)
        if match_sub:
            core_cookies["SUB"] = match_sub.group(1)
        if not core_cookies:
            for pair in cookie_string.split(";"):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    core_cookies[key.strip()] = value.strip()
        self.session.cookies.update(core_cookies)
        try:
            self.session.get("https://m.weibo.cn", headers=self.headers, timeout=10)
            logger.info("Session warm-up successful")
        except Exception as e:
            logger.warning(f"Session warm-up failed: {e}")

    def _validate_cookie(self):
        """Validate cookie by fetching a known endpoint. Raises if invalid."""
        try:
            url = "https://m.weibo.cn/api/config"
            resp = self.session.get(url, headers=self._get_random_headers(), timeout=10)
            js = resp.json()
            if not js.get("data", {}).get("login"):
                raise ValueError(
                    "Cookie is invalid or expired (not logged in). "
                    "Please update your WEIBO_COOKIE."
                )
            screen_name = js["data"].get("user", {}).get("screen_name", "unknown")
            logger.info(f"Cookie validated, logged in as: {screen_name}")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"Cookie validation failed: {e}")

    def _get_random_headers(self) -> dict:
        """Return headers with randomized User-Agent."""
        headers = self.headers.copy()
        headers["User-Agent"] = random.choice(self.config.anti_ban.user_agents)
        return headers

    def _dynamic_delay(self):
        """Apply dynamic delay between requests."""
        if not self.config.anti_ban.enabled:
            return
        min_delay = self.config.anti_ban.request_delay_min
        max_delay = self.config.anti_ban.request_delay_max
        delay = random.uniform(min_delay, max_delay)
        if self.request_count > 100:
            delay *= 1.5
        logger.debug(f"Sleeping {delay:.1f}s (anti-ban)")
        time.sleep(delay)

    def _should_pause(self) -> bool:
        """Check if we should pause due to anti-ban thresholds."""
        if not self.config.anti_ban.enabled:
            return False
        if self.api_errors >= self.config.anti_ban.max_api_errors:
            return True
        if self.start_time:
            elapsed = time.time() - self.start_time
            if elapsed >= self.config.anti_ban.max_session_time:
                return True
        return False

    def _perform_rest(self):
        """Perform anti-ban rest period."""
        rest_time = self.config.anti_ban.rest_time_min + random.randint(0, 60)
        logger.info(f"Anti-ban rest: sleeping {rest_time}s")
        time.sleep(rest_time)
        self.api_errors = 0
        self.start_time = time.time()

    def get_user_info(self, user_id: str) -> dict:
        """Fetch user profile info."""
        self._ensure_cookie()
        params = {"containerid": "100505" + str(user_id)}
        url = "https://m.weibo.cn/api/container/getIndex"
        max_retries = 5
        for retry in range(max_retries):
            try:
                self._dynamic_delay()
                resp = self.session.get(
                    url, params=params, headers=self._get_random_headers(), timeout=10
                )
                resp.raise_for_status()
                js = resp.json()
                self.request_count += 1

                if "data" in js and "userInfo" in js["data"]:
                    info = js["data"]["userInfo"]
                    return {
                        "id": user_id,
                        "screen_name": info.get("screen_name", ""),
                        "description": info.get("description", ""),
                        "statuses_count": info.get("statuses_count", 0),
                        "followers_count": info.get("followers_count", 0),
                        "verified": info.get("verified", False),
                        "verified_reason": info.get("verified_reason", ""),
                    }
                else:
                    logger.warning(f"No user info for {user_id}, retry {retry+1}")
            except Exception as e:
                logger.error(f"get_user_info error: {e}, retry {retry+1}")
                time.sleep(5 * (2 ** retry))
                self.api_errors += 1
        return {}

    def _parse_html_text(self, html_text: str) -> str:
        """Parse HTML formatted weibo text into plain text."""
        try:
            selector = etree.HTML(html_text if not html_text.isspace() else f"{html_text}<hr>")
            text_list = selector.xpath("//text()")
            merged = []
            for i, t in enumerate(text_list):
                if i > 0 and (text_list[i - 1].startswith(("@", "#")) or t.startswith(("@", "#"))):
                    merged[-1] += t
                else:
                    merged.append(t)
            return "\n".join(merged)
        except Exception:
            return html_text

    def _parse_weibo_text(self, weibo_info: dict) -> dict:
        """Parse a weibo card into a text-only record."""
        weibo = {}
        if weibo_info.get("user"):
            weibo["user_id"] = str(weibo_info["user"]["id"])
            weibo["screen_name"] = weibo_info["user"]["screen_name"]
        else:
            weibo["user_id"] = ""
            weibo["screen_name"] = ""
        weibo["id"] = str(weibo_info["id"])
        weibo["bid"] = weibo_info.get("bid", "")

        # Check if text is truncated (long weibo)
        text_body = weibo_info.get("text", "")
        is_long = weibo_info.get("isLongText", False)
        if is_long:
            long_text = self._get_long_weibo_text(weibo["id"])
            if long_text:
                text_body = long_text

        weibo["text"] = self._parse_html_text(text_body)

        weibo["created_at"] = weibo_info.get("created_at", "")
        weibo["source"] = weibo_info.get("source", "")
        weibo["attitudes_count"] = weibo_info.get("attitudes_count", 0)
        weibo["comments_count"] = weibo_info.get("comments_count", 0)
        weibo["reposts_count"] = weibo_info.get("reposts_count", 0)

        try:
            topics = re.findall(r"#(.*?)#", weibo["text"])
            weibo["topics"] = ",".join(topics)
            at_users = re.findall(r"@([\w\u4e00-\u9fff]+)", weibo["text"])
            weibo["at_users"] = ",".join(at_users)
        except Exception:
            weibo["topics"] = ""
            weibo["at_users"] = ""

        return weibo

    def _get_weibo_json(self, user_id: str, page: int) -> dict:
        """Fetch one page of weibo JSON for a user."""
        url = "https://m.weibo.cn/api/container/getIndex"
        params = {
            "type": "uid",
            "value": str(user_id),
            "containerid": "107603" + str(user_id),
            "page": page,
            "count": self.config.page_weibo_count,
        }
        max_retries = 5
        for retry in range(max_retries):
            try:
                self._dynamic_delay()
                resp = self.session.get(
                    url, params=params, headers=self._get_random_headers(), timeout=10
                )
                resp.raise_for_status()
                js = resp.json()
                self.request_count += 1
                if "data" in js:
                    return js
                elif js.get("ok") == 0:
                    msg = js.get("msg", "")
                    if "请登录" in msg or "login" in msg.lower():
                        raise ValueError("Cookie expired during crawl. Please update WEIBO_COOKIE.")
                    logger.warning(f"API returned ok=0 for user {user_id} page {page}: {msg}")
                    return {}
                else:
                    logger.warning(f"No data in response for user {user_id} page {page}")
                    return {}
            except ValueError:
                raise
            except Exception as e:
                logger.error(f"get_weibo_json error: {e}, retry {retry+1}")
                time.sleep(5 * min(2 ** retry, 6))  # cap backoff at 30s
                self.api_errors += 1
        return {}

    def _get_long_weibo_text(self, weibo_id: str) -> str:
        """Fetch full text for long weibos via statuses/extend API."""
        url = "https://m.weibo.cn/statuses/extend"
        params = {"id": weibo_id}
        try:
            self._dynamic_delay()
            resp = self.session.get(
                url, params=params, headers=self._get_random_headers(), timeout=10
            )
            js = resp.json()
            self.request_count += 1
            if js.get("ok") == 1 and "data" in js:
                return js["data"].get("longTextContent", "")
        except Exception as e:
            logger.debug(f"Failed to get long weibo text for {weibo_id}: {e}")
        return ""

    def _standardize_date(self, created_at: str) -> str:
        """Standardize Weibo date formats to DTFORMAT."""
        if not created_at:
            return ""
        if re.match(r"\d{4}-\d{2}-\d{2}T", created_at):
            return created_at
        if "秒前" in created_at or "刚刚" in created_at:
            return datetime.now().strftime(DTFORMAT)
        if "分钟前" in created_at:
            minutes = int(re.findall(r"\d+", created_at)[0])
            dt = datetime.now() - timedelta(minutes=minutes)
            return dt.strftime(DTFORMAT)
        if "小时前" in created_at:
            hours = int(re.findall(r"\d+", created_at)[0])
            dt = datetime.now() - timedelta(hours=hours)
            return dt.strftime(DTFORMAT)
        if "今天" in created_at:
            time_part = re.findall(r"\d{2}:\d{2}", created_at)
            if time_part:
                return datetime.now().strftime("%Y-%m-%d") + "T" + time_part[0] + ":00"
        if re.match(r"\d{2}-\d{2}$", created_at):
            return f"{datetime.now().year}-{created_at}T00:00:00"
        try:
            for fmt in ["%a %b %d %H:%M:%S %z %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]:
                try:
                    dt = datetime.strptime(created_at, fmt)
                    return dt.strftime(DTFORMAT)
                except ValueError:
                    continue
        except Exception:
            pass
        return created_at

    def _get_output_path(self, filename: str) -> str:
        """Get full output path for a weibo JSON file."""
        return os.path.join(self.config.knowledge_dir(), "weibo", filename)

    def collect_user_weibos(self, user_id: str, filename: str = None,
                            source_account: str = None) -> list:
        """Collect all weibo texts for a user with incremental save.

        Args:
            user_id: Weibo user ID to collect from.
            filename: If provided, enables incremental save to this file.
                      Loads existing data to avoid duplicates and saves after each page.
            source_account: If provided, set as source_account on each weibo
                            before incremental save.

        Returns:
            List of all collected weibo dicts (including previously saved ones).
        """
        self.start_time = time.time()
        self.request_count = 0
        self.api_errors = 0

        user_info = self.get_user_info(user_id)
        if not user_info:
            logger.error(f"Cannot get user info for {user_id}")
            return []

        screen_name = user_info.get("screen_name", user_id)
        total_count = user_info.get("statuses_count", 0)
        logger.info(f"Collecting weibos for {screen_name} (id={user_id}), total ~{total_count}")

        # Load existing data to avoid duplicates
        output_path = self._get_output_path(filename) if filename else None
        if output_path:
            all_weibos, weibo_ids_seen = load_json_list(output_path)
            if weibo_ids_seen:
                logger.info(f"Loaded {len(all_weibos)} existing weibos, resuming collection")
        else:
            all_weibos = []
            weibo_ids_seen = set()

        # Resume from last page if metadata exists
        page = 1
        if output_path:
            meta = load_resume_meta(output_path)
            saved_page = meta.get("last_page", 0)
            if saved_page > 1 and weibo_ids_seen:
                page = max(1, saved_page - 2)  # overlap to catch boundary shifts
                logger.info(f"Resuming from page {page} (saved: {saved_page})")

        empty_pages = 0
        new_count_this_session = 0

        while True:
            if self._should_pause():
                self._perform_rest()

            js = self._get_weibo_json(user_id, page)
            if not js or "data" not in js:
                empty_pages += 1
                if empty_pages >= 3:
                    logger.info(f"3 consecutive empty pages, stopping for {screen_name}")
                    break
                page += 1
                continue

            empty_pages = 0
            cards = js["data"].get("cards", [])
            found_any = False
            page_new_count = 0

            for card in cards:
                if card.get("card_type") == 11:
                    card_group = card.get("card_group", [])
                    if card_group:
                        card = card_group[0]

                if card.get("card_type") != 9:
                    continue

                mblog = card.get("mblog")
                if not mblog:
                    continue

                wb = self._parse_weibo_text(mblog)
                wb_id = wb["id"]

                if wb_id in weibo_ids_seen:
                    continue

                if source_account:
                    wb["source_account"] = source_account
                wb["created_at"] = self._standardize_date(wb["created_at"])

                if wb["created_at"]:
                    try:
                        created = datetime.strptime(wb["created_at"], DTFORMAT)
                        # end_date filter: skip weibos newer than end_date
                        if self.config.end_date:
                            end_dt = datetime.strptime(
                                self.config.end_date + "T23:59:59"
                                if "T" not in self.config.end_date
                                else self.config.end_date,
                                DTFORMAT,
                            )
                            if created > end_dt:
                                continue
                        # since_date filter: stop at weibos older than since_date
                        if self.config.since_date:
                            since = datetime.strptime(
                                self.config.since_date + "T00:00:00"
                                if "T" not in self.config.since_date
                                else self.config.since_date,
                                DTFORMAT,
                            )
                            if created < since:
                                if mblog.get("mblogtype") == 2:
                                    continue
                                logger.info(f"Reached since_date for {screen_name}")
                                if output_path:
                                    safe_json_save(all_weibos, output_path)
                                    clear_resume_meta(output_path)
                                return all_weibos
                    except ValueError:
                        pass

                weibo_ids_seen.add(wb_id)
                all_weibos.append(wb)
                found_any = True
                page_new_count += 1

            new_count_this_session += page_new_count

            # Incremental save after each page with new data
            if output_path and page_new_count > 0:
                safe_json_save(all_weibos, output_path)
                save_resume_meta(output_path, {"last_page": page})

            if not found_any and not cards:
                break

            page += 1
            logger.info(
                f"Page {page-1} done, +{page_new_count} new, "
                f"{len(all_weibos)} total for {screen_name}"
            )

        # Final save
        if output_path:
            safe_json_save(all_weibos, output_path)
            clear_resume_meta(output_path)

        logger.info(
            f"Collected {new_count_this_session} new weibos for {screen_name} "
            f"({len(all_weibos)} total)"
        )
        return all_weibos

    def collect_all_idol_weibos(self) -> list:
        """Collect weibos from all idol accounts with incremental save.

        When there is only one idol account, saves directly to idol_weibos.json
        to avoid duplicate files. When there are multiple accounts, saves
        per-account files for incremental resume, then merges into idol_weibos.json.
        """
        all_weibos = []
        single = len(self.config.idol_weibo_ids) == 1

        for idol_id in self.config.idol_weibo_ids:
            # Single idol: save directly as idol_weibos.json (no per-account file)
            # Multiple idols: save per-account for incremental resume
            filename = "idol_weibos.json" if single else f"idol_{idol_id}.json"
            weibos = self.collect_user_weibos(
                idol_id, filename=filename, source_account=idol_id
            )
            all_weibos.extend(weibos)

        # Merge per-account files into idol_weibos.json (only needed for multiple accounts)
        if not single and all_weibos:
            self.save_weibos(all_weibos, "idol_weibos.json")

        return all_weibos

    def save_weibos(self, weibos: list, filename: str):
        """Save weibos to JSON file in knowledge/weibo/. Protects against empty overwrite."""
        output_path = self._get_output_path(filename)
        safe_json_save(weibos, output_path)
        logger.info(f"Saved {len(weibos)} weibos to {output_path}")
