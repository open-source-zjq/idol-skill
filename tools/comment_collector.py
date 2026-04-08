"""Comment collector: fetches idol reply-fan comment conversation pairs.

Uses cookie-based hotflow API. Cookie is required.
Extracts idol replies from hotflow's inline `comments` array and pairs
each with the fan comment it responds to.
"""

import logging
import os
import random
import time

import requests
from lxml import etree
from tools.config_manager import IdolConfig
from tools.persistence import load_json_dict, safe_json_save

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when the Weibo API rate-limits comment fetching."""
    pass


class CommentCollector:
    """Collects idol comment replies paired with fan context."""

    def __init__(self, config: IdolConfig, session: requests.Session = None):
        self.config = config
        self.idol_ids = set(str(i) for i in config.idol_weibo_ids)
        self.session = session or requests.Session()

        self._cookie_ready = False
        cookie = config.get_cookie()
        if cookie:
            self._setup_cookie(cookie)
            self._cookie_ready = True

        self.headers = {
            "Referer": "https://m.weibo.cn/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": random.choice(config.anti_ban.user_agents),
            "X-Requested-With": "XMLHttpRequest",
        }

    @property
    def has_cookie(self) -> bool:
        """Check if a valid cookie has been set."""
        return self._cookie_ready

    def set_cookie(self, cookie_string: str):
        """Set cookie after initialization."""
        self._setup_cookie(cookie_string)
        self._cookie_ready = True

    def _ensure_cookie(self):
        """Raise if cookie is not set. Call before any API request."""
        if not self._cookie_ready:
            raise ValueError(
                "Weibo cookie not set. Call set_cookie() first or set WEIBO_COOKIE env var."
            )

    def _setup_cookie(self, cookie_string: str):
        """Parse and set cookie on session."""
        for pair in cookie_string.split(";"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                self.session.cookies.set(key.strip(), value.strip())

    def _delay(self):
        """Random delay between requests."""
        min_delay = max(2, self.config.anti_ban.request_delay_min // 3)
        max_delay = max(5, self.config.anti_ban.request_delay_max // 3)
        time.sleep(random.uniform(min_delay, max_delay))

    def _get_comments(self, weibo_id: str, max_count: int):
        """Fetch comments using cookie-based hotflow API.

        Tries hotflow first, falls back to comments/show pagination API.

        Returns:
            list: raw comments on success (may be empty)
            None: on request failure from both APIs
        """
        result = self._get_comments_hotflow(weibo_id, max_count)
        if result is not None:
            return result
        return self._get_comments_show(weibo_id, max_count)

    def _get_comments_hotflow(self, weibo_id: str, max_count: int):
        """Fetch comments via hotflow API (requires cookie).

        Returns:
            list: comments on success (may be empty if post has none)
            None: on request failure (network error, non-JSON, rate limit)
        """
        all_comments = []
        max_id = None

        while len(all_comments) < max_count:
            url = "https://m.weibo.cn/comments/hotflow"
            params = {"mid": weibo_id, "max_id_type": 0}
            if max_id:
                params["max_id"] = max_id

            try:
                self._delay()
                resp = self.session.get(url, params=params, headers=self.headers, timeout=10)
                if resp.status_code != 200:
                    logger.warning(f"Hotflow HTTP {resp.status_code} for {weibo_id}")
                    return None
                # Check for non-JSON response (HTML login page, etc.)
                content_type = resp.headers.get("Content-Type", "")
                if "json" not in content_type and "javascript" not in content_type:
                    logger.warning(f"Hotflow non-JSON response for {weibo_id}: {content_type}")
                    return None
                js = resp.json()
            except Exception as e:
                logger.warning(f"Hotflow comment fetch failed for {weibo_id}: {e}")
                return None

            if js.get("ok") != 1:
                msg = js.get("msg", "")
                logger.debug(f"Hotflow ok!=1 for {weibo_id}: {msg}")
                return None

            data = js.get("data")
            if not data:
                return all_comments  # valid response, just no data

            comments = data.get("data", [])
            if not comments:
                break

            all_comments.extend(comments)
            max_id = data.get("max_id", 0)
            if max_id == 0:
                break

        return all_comments[:max_count]

    def _get_comments_show(self, weibo_id: str, max_count: int):
        """Fetch comments via comments/show pagination API (fallback).

        Returns:
            list: comments on success (may be empty if post has none)
            None: on request failure (network error, non-JSON, rate limit)
        """
        all_comments = []
        page = 1

        while len(all_comments) < max_count:
            url = "https://m.weibo.cn/api/comments/show"
            params = {"id": weibo_id, "page": page}
            try:
                self._delay()
                resp = self.session.get(url, params=params, headers=self.headers, timeout=10)
                if resp.status_code != 200:
                    logger.warning(f"Comments/show HTTP {resp.status_code} for {weibo_id}")
                    return None
                content_type = resp.headers.get("Content-Type", "")
                if "json" not in content_type and "javascript" not in content_type:
                    logger.warning(f"Comments/show non-JSON response for {weibo_id}: {content_type}")
                    return None
                js = resp.json()
            except Exception as e:
                logger.warning(f"Comments/show fetch failed for {weibo_id}: {e}")
                return None

            if js.get("ok") != 1:
                return None

            data = js.get("data")
            if not data:
                break

            comments = data.get("data", [])
            if not comments:
                break

            all_comments.extend(comments)
            page += 1
            max_page = data.get("max", 0)
            if page > max_page:
                break

        return all_comments[:max_count]

    def _clean_html(self, html_text: str) -> str:
        """Strip HTML tags from comment text, keeping only plain text."""
        if not html_text:
            return ""
        try:
            selector = etree.HTML(html_text)
            text_parts = selector.xpath("//text()")
            return "".join(text_parts)
        except Exception:
            return html_text

    def _strip_reply_prefix(self, text: str) -> tuple:
        """Strip '回复@screen_name:' prefix from comment text.

        Returns:
            (screen_name, clean_text) if prefix found,
            ("", original_text) otherwise.
        """
        import re
        m = re.match(r"回复@(.+?)[:：](.*)$", text, re.DOTALL)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return "", text

    def _is_idol(self, comment: dict) -> bool:
        """Check if a comment is from the idol."""
        user_id = str(comment.get("user", {}).get("id", ""))
        return user_id in self.idol_ids

    def _parse_idol_comment(self, comment: dict, fan_context: dict = None) -> dict:
        """Parse an idol comment into structured format with fan context."""
        user = comment.get("user", {})
        text = self._clean_html(comment.get("text", ""))
        # Strip "回复@xxx:" prefix (common in comments/show responses)
        _, text = self._strip_reply_prefix(text)
        like_count = comment.get("like_count", comment.get("like_counts", 0))
        return {
            "id": str(comment.get("id", "")),
            "user_id": str(user.get("id", "")),
            "screen_name": user.get("screen_name", ""),
            "text": text,
            "created_at": comment.get("created_at", ""),
            "like_count": like_count,
            "fan_context": fan_context,
        }

    def _extract_idol_comments(self, raw_comments: list) -> list:
        """Extract idol comments paired with fan context from raw API response.

        Handles two API formats:
        - Hotflow: idol replies in nested `comments` array under fan comments.
        - Comments/show: flat list with `reply_text` field for the replied-to
          comment. Two sub-cases:
          (a) Current comment user IS idol → idol text in `text`, fan in `reply_text`.
          (b) Current comment user is fan, replying to idol → idol text in
              `reply_text`, fan text in `text`. Matched via `reply_id`.

        Pure fan comments with no idol involvement are discarded.
        """
        idol_comments = []
        # Track extracted idol comment IDs to dedup
        seen_ids = set()

        # --- Pass 1: hotflow nested + idol's own comments ---
        for raw in raw_comments:
            inner_replies = raw.get("comments") or []
            if not isinstance(inner_replies, list):
                inner_replies = []
            idol_replies = [r for r in inner_replies if self._is_idol(r)]

            if idol_replies:
                # Hotflow: idol replied to this fan comment
                fan_user = raw.get("user", {})
                fan_context = {
                    "screen_name": fan_user.get("screen_name", ""),
                    "text": self._clean_html(raw.get("text", "")),
                }
                for reply in idol_replies:
                    cid = str(reply.get("id", ""))
                    if cid not in seen_ids:
                        seen_ids.add(cid)
                        idol_comments.append(
                            self._parse_idol_comment(reply, fan_context=fan_context)
                        )
            elif self._is_idol(raw):
                # Comments/show case (a): idol comment with reply_text as fan context
                cid = str(raw.get("id", ""))
                if cid in seen_ids:
                    continue
                seen_ids.add(cid)
                fan_context = None
                reply_text = raw.get("reply_text")
                if reply_text:
                    idol_text_clean = self._clean_html(raw.get("text", ""))
                    fan_name, _ = self._strip_reply_prefix(idol_text_clean)
                    fan_text = self._clean_html(reply_text)
                    _, fan_text = self._strip_reply_prefix(fan_text)
                    fan_context = {
                        "screen_name": fan_name,
                        "text": fan_text,
                    }
                idol_comments.append(
                    self._parse_idol_comment(raw, fan_context=fan_context)
                )

        # Note: comments/show also contains 3rd-layer fan follow-ups
        # (fan replying to idol's reply). These are discarded — they lack
        # the original fan comment and have no distillation value.

        return idol_comments

    def collect_comments(self, weibo_id: str, weibo_comments_count: int = 0):
        """Collect idol comments for a weibo post, paired with fan context.

        Raises ValueError if cookie is not set.

        Returns:
            list: idol comments with fan_context on success (may be empty)
            None: on request failure (API error, rate limit)
        """
        self._ensure_cookie()

        if weibo_comments_count == 0:
            return []

        max_count = self.config.comment_max_count
        raw_comments = self._get_comments(weibo_id, max_count)

        if raw_comments is None:
            return None  # propagate failure

        if not raw_comments:
            return []  # valid empty result

        idol_comments = self._extract_idol_comments(raw_comments)

        logger.info(f"Collected {len(idol_comments)} idol comments for weibo {weibo_id}")
        return idol_comments

    def collect_comments_for_weibos(self, weibos: list, filename: str = None,
                                    max_consecutive_failures: int = 5) -> dict:
        """Collect comments for a list of weibos with incremental save.

        Args:
            weibos: List of weibo dicts to collect comments for.
            filename: If provided, enables incremental save and dedup.
            max_consecutive_failures: Stop after this many consecutive
                weibos return no comments (likely rate-limited). Default 5.

        Returns:
            Dict mapping weibo_id -> idol comment list.

        Raises:
            RateLimitError: When consecutive failures reach the threshold,
                indicating the API is rate-limiting requests.
        """
        output_path = (
            os.path.join(self.config.knowledge_dir(), "comments", filename)
            if filename else None
        )

        # Load existing to skip already-collected weibos
        if output_path:
            all_comments = load_json_dict(output_path)
            existing_count = len(all_comments)
            if existing_count:
                logger.info(f"Loaded existing comments for {existing_count} weibos, resuming")
        else:
            all_comments = {}

        consecutive_failures = 0

        for wb in weibos:
            weibo_id = wb["id"]

            # Skip if already collected
            if weibo_id in all_comments:
                continue

            comments_count = wb.get("comments_count", 0)
            if comments_count == 0:
                continue

            comments = self.collect_comments(weibo_id, comments_count)
            if comments is None:
                # Request failed (API error / rate limit)
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    # Save what we have before raising
                    if output_path:
                        safe_json_save(all_comments, output_path)
                    raise RateLimitError(
                        f"评论采集被限流：连续 {consecutive_failures} 条微博的评论均获取失败。"
                        f"已保存 {len(all_comments)} 条微博的评论。"
                        f"请稍后重试，或更换 Cookie。"
                    )
            else:
                # Success (may be empty list if no idol comments)
                consecutive_failures = 0
                if comments:
                    all_comments[weibo_id] = comments
                    if output_path:
                        safe_json_save(all_comments, output_path)

        # Final save
        if output_path:
            safe_json_save(all_comments, output_path)

        return all_comments

    def save_comments(self, comments: dict, filename: str):
        """Save comments dict to JSON file in knowledge/comments/."""
        output_path = os.path.join(self.config.knowledge_dir(), "comments", filename)
        safe_json_save(comments, output_path)
        logger.info(f"Saved comments for {len(comments)} weibos to {output_path}")
