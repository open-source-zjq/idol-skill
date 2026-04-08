"""Style corpus builder.

Collects all idol speech into a unified style corpus for LLM analysis.
Sources: idol weibo posts + idol comment replies (with fan context).
"""

import logging
import os

from tools.config_manager import IdolConfig
from tools.persistence import safe_json_save

logger = logging.getLogger(__name__)


class StyleCorpusBuilder:
    """Builds style learning corpus from idol's public content."""

    def __init__(self, config: IdolConfig):
        self.config = config
        self.idol_ids = set(str(i) for i in config.idol_weibo_ids)

    def build(self, weibos: list, comments: dict = None) -> list:
        """Build style corpus from weibos and comments.

        Args:
            weibos: List of idol's weibo posts
            comments: Dict mapping weibo_id -> idol comment list (optional).
                      Each comment has fan_context (paired fan comment) or None.

        Returns:
            List of style corpus entries
        """
        if comments is None:
            comments = {}

        corpus = []

        # Add weibo posts
        for wb in weibos:
            if str(wb.get("user_id", "")) not in self.idol_ids:
                continue
            corpus.append({
                "id": wb["id"],
                "source_account": wb.get("source_account", wb.get("user_id", "")),
                "type": "post",
                "text": wb["text"],
                "reply_to": "",
                "created_at": wb.get("created_at", ""),
                "context": "",
            })

        # Add idol comment replies
        if comments:
            weibo_text_map = {wb["id"]: wb["text"][:200] for wb in weibos}
            for weibo_id, comment_list in comments.items():
                weibo_context = weibo_text_map.get(weibo_id, "")
                for comment in comment_list:
                    fan_context = comment.get("fan_context")
                    if fan_context:
                        context = fan_context.get("text", "")
                        reply_to = fan_context.get("screen_name", "")
                    else:
                        context = weibo_context
                        reply_to = ""
                    corpus.append({
                        "id": comment.get("id", ""),
                        "source_account": comment.get("user_id", ""),
                        "type": "comment_reply",
                        "text": comment.get("text", ""),
                        "reply_to": reply_to,
                        "created_at": comment.get("created_at", ""),
                        "context": context,
                    })

        corpus.sort(key=lambda x: x.get("created_at", ""))

        logger.info(f"Built style corpus with {len(corpus)} entries "
                    f"({sum(1 for c in corpus if c['type'] == 'post')} posts, "
                    f"{sum(1 for c in corpus if c['type'] == 'comment_reply')} replies)")
        return corpus

    def save(self, corpus: list):
        """Save style corpus to JSON."""
        output_path = os.path.join(self.config.data_dir(), "style_corpus.json")
        safe_json_save(corpus, output_path)
        logger.info(f"Saved style corpus ({len(corpus)} entries) to {output_path}")
