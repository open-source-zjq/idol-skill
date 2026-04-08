"""Skill file writer and version manager for idol-skill.

Handles:
- Creating/updating idol directories and files
- Generating SKILL.md from style.md
- Version backup and rollback
- meta.json management
"""

import json
import logging
import os
import shutil
from datetime import datetime

from tools.persistence import atomic_json_write

logger = logging.getLogger(__name__)


class SkillWriter:
    """Manages idol skill file I/O and versioning."""

    def __init__(self, base_dir: str = "idols"):
        self.base_dir = base_dir

    def idol_dir(self, slug: str) -> str:
        return os.path.join(self.base_dir, slug)

    def write_meta(self, slug: str, meta: dict):
        """Write meta.json."""
        path = os.path.join(self.idol_dir(slug), "meta.json")
        meta["updated_at"] = datetime.now().isoformat()
        atomic_json_write(meta, path)
        logger.info(f"Written meta.json for {slug}")

    def read_meta(self, slug: str) -> dict:
        """Read meta.json."""
        path = os.path.join(self.idol_dir(slug), "meta.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def write_style(self, slug: str, content: str):
        """Write style.md."""
        path = os.path.join(self.idol_dir(slug), "style.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Written style.md for {slug}")

    def generate_skill_md(self, slug: str, meta: dict, style_content: str) -> str:
        """Generate the final SKILL.md content."""
        stage_name = meta.get("profile", {}).get("stage_name", meta.get("name", slug))
        group = meta.get("profile", {}).get("group", "")
        description = f"{stage_name}"
        if group:
            description += f"，来自{group}的地下偶像"

        return f"""---
name: idol_{slug}
description: "{description}"
user-invocable: true
---

# {stage_name}

{description}

---

{style_content}

---

## 运行规则

1. 使用上述风格画像中的语气、措辞、表达习惯来生成回应
2. 不编造具体经历或事实
3. 身份边界：你是基于公开内容蒸馏出的"偶像风格陪伴对话"，不是在伪造真人身份
4. Layer 0 优先：核心语气规则优先级最高，任何情况下不得违背
5. 恋爱禁止条例：当用户提及交往、告白、求婚、约会等恋爱话题时，以偶像风格自然地回避或转移话题
"""

    def write_skill(self, slug: str, meta: dict, style_content: str):
        """Generate and write SKILL.md."""
        content = self.generate_skill_md(slug, meta, style_content)
        path = os.path.join(self.idol_dir(slug), "SKILL.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Written SKILL.md for {slug}")

    def backup_version(self, slug: str) -> str:
        """Backup current version before update. Returns the version label."""
        meta = self.read_meta(slug)
        version = meta.get("version", "v0")
        version_dir = os.path.join(self.idol_dir(slug), "versions", version)
        os.makedirs(version_dir, exist_ok=True)
        for filename in ["SKILL.md", "style.md", "meta.json"]:
            src = os.path.join(self.idol_dir(slug), filename)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(version_dir, filename))
        logger.info(f"Backed up {slug} version {version}")
        return version

    def rollback(self, slug: str, version: str) -> bool:
        """Rollback to a specific version."""
        version_dir = os.path.join(self.idol_dir(slug), "versions", version)
        if not os.path.exists(version_dir):
            logger.error(f"Version {version} not found for {slug}")
            return False
        self.backup_version(slug)
        for filename in ["SKILL.md", "style.md", "meta.json"]:
            src = os.path.join(version_dir, filename)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(self.idol_dir(slug), filename))
        logger.info(f"Rolled back {slug} to version {version}")
        return True

    def increment_version(self, slug: str) -> str:
        """Increment version number in meta.json."""
        meta = self.read_meta(slug)
        current = meta.get("version", "v0")
        num = int(current.replace("v", "")) + 1
        new_version = f"v{num}"
        meta["version"] = new_version
        self.write_meta(slug, meta)
        return new_version

    def list_idols(self) -> list:
        """List all created idol skills."""
        if not os.path.exists(self.base_dir):
            return []
        idols = []
        for name in sorted(os.listdir(self.base_dir)):
            meta_path = os.path.join(self.base_dir, name, "meta.json")
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                idols.append({
                    "slug": name,
                    "name": meta.get("name", name),
                    "stage_name": meta.get("profile", {}).get("stage_name", ""),
                    "group": meta.get("profile", {}).get("group", ""),
                    "version": meta.get("version", "v1"),
                    "updated_at": meta.get("updated_at", ""),
                })
        return idols
