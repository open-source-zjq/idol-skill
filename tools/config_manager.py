"""Configuration management for idol-skill."""

import json
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AntiBanConfig:
    """Anti-ban settings for Weibo scraping."""
    enabled: bool = True
    max_weibo_per_session: int = 500
    batch_size: int = 50
    batch_delay: int = 30
    request_delay_min: int = 8
    request_delay_max: int = 15
    max_session_time: int = 600
    max_api_errors: int = 5
    rest_time_min: int = 180
    random_rest_probability: float = 0.01
    user_agents: list = field(default_factory=lambda: [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    ])


@dataclass
class IdolConfig:
    """Configuration for a single idol skill build."""
    idol_name: str
    slug: str
    idol_weibo_ids: list
    cookie: Optional[str] = None
    since_date: str = "2020-01-01"
    end_date: str = ""
    output_dir: str = "idols"
    anti_ban: AntiBanConfig = field(default_factory=AntiBanConfig)
    comment_max_count: int = 200
    page_weibo_count: int = 20

    @classmethod
    def from_dict(cls, data: dict) -> "IdolConfig":
        data = dict(data)  # Don't mutate caller's dict
        anti_ban_data = data.pop("anti_ban", {})
        anti_ban = AntiBanConfig(**anti_ban_data) if anti_ban_data else AntiBanConfig()
        return cls(anti_ban=anti_ban, **data)

    def idol_dir(self) -> str:
        return os.path.join(self.output_dir, self.slug)

    def knowledge_dir(self) -> str:
        return os.path.join(self.idol_dir(), "knowledge")

    def data_dir(self) -> str:
        return os.path.join(self.idol_dir(), "data")

    def ensure_dirs(self):
        """Create all required directories for this idol."""
        dirs = [
            os.path.join(self.knowledge_dir(), "weibo"),
            os.path.join(self.knowledge_dir(), "comments"),
            self.data_dir(),
            os.path.join(self.idol_dir(), "versions"),
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)

    def get_cookie(self) -> Optional[str]:
        """Get cookie from env var or config, env var takes priority.

        Cookie is required for Weibo data collection.
        Set WEIBO_COOKIE env var or provide cookie in config.
        """
        return os.environ.get("WEIBO_COOKIE") or self.cookie
