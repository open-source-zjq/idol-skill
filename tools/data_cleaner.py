"""Data cleaner for weibo posts and comments.

Removes duplicates, empty content, system messages, and normalizes text.
"""

import logging
import re

logger = logging.getLogger(__name__)


class DataCleaner:
    """Cleans and normalizes weibo data."""

    NOISE_PATTERNS = [
        r"^转发微博$",
        r"^分享图片$",
        r"^分享视频$",
        r"^\s*$",
        r"^Repost$",
    ]

    def __init__(self):
        self.compiled_noise = [re.compile(p) for p in self.NOISE_PATTERNS]

    def _is_noise(self, text: str) -> bool:
        """Check if text is noise/system content."""
        text = text.strip()
        if not text:
            return True
        for pattern in self.compiled_noise:
            if pattern.match(text):
                return True
        return False

    def _normalize_text(self, text: str) -> str:
        """Normalize whitespace and remove unnecessary chars."""
        text = text.strip()
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r" {2,}", " ", text)
        return text

    def clean_weibos(self, weibos: list) -> list:
        """Clean weibo list: deduplicate and remove noise. Returns new cleaned list."""
        seen_ids = set()
        seen_texts = set()
        cleaned = []

        for wb in weibos:
            wb_id = wb.get("id", "")
            text = wb.get("text", "")

            if wb_id in seen_ids:
                continue
            if self._is_noise(text):
                continue

            text_normalized = self._normalize_text(text)
            if text_normalized in seen_texts:
                continue

            seen_ids.add(wb_id)
            seen_texts.add(text_normalized)

            wb = dict(wb)
            wb["text"] = text_normalized
            cleaned.append(wb)

        removed = len(weibos) - len(cleaned)
        if removed > 0:
            logger.info(f"Cleaned weibos: {len(weibos)} -> {len(cleaned)} (removed {removed})")
        return cleaned

    def clean_comments(self, comments: dict) -> dict:
        """Clean comments dict: remove noise, deduplicate, normalize text.

        Comments are flat lists of idol comments with optional fan_context.
        """
        cleaned = {}
        for weibo_id, comment_list in comments.items():
            cleaned_list = self._clean_comment_list(comment_list)
            if cleaned_list:
                cleaned[weibo_id] = cleaned_list
        return cleaned

    def _clean_comment_list(self, comments: list) -> list:
        """Clean a flat list of idol comments."""
        cleaned = []
        seen_ids = set()

        for comment in comments:
            cid = comment.get("id", "")
            text = comment.get("text", "")

            if cid in seen_ids:
                continue
            if self._is_noise(text):
                continue

            seen_ids.add(cid)
            comment = dict(comment)
            comment["text"] = self._normalize_text(text)

            # Normalize fan_context text if present
            fan_context = comment.get("fan_context")
            if fan_context and fan_context.get("text"):
                fan_context = dict(fan_context)
                fan_context["text"] = self._normalize_text(fan_context["text"])
                comment["fan_context"] = fan_context

            cleaned.append(comment)

        return cleaned
