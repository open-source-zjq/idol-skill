"""Shared persistence utilities for incremental save with atomic writes."""

import json
import logging
import os
import tempfile

logger = logging.getLogger(__name__)


def atomic_json_write(data, filepath: str):
    """Write JSON data to file atomically via temp file + os.replace.

    Ensures that a crash mid-write never corrupts the target file.
    """
    dirpath = os.path.dirname(filepath)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dirpath or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, filepath)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def safe_json_save(data, filepath: str):
    """Save JSON data, refusing to overwrite non-empty file with empty data."""
    is_empty = (isinstance(data, list) and not data) or (isinstance(data, dict) and not data)
    if is_empty:
        try:
            if os.path.getsize(filepath) > 2:
                logger.warning(f"Refusing to overwrite non-empty {filepath} with empty data")
                return
        except OSError:
            pass
    atomic_json_write(data, filepath)


def load_json_list(filepath: str) -> tuple:
    """Load a JSON list file. Returns (list, set of 'id' values)."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            ids = {str(item["id"]) for item in data if "id" in item}
            return data, ids
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to load existing data from {filepath}: {e}")
    return [], set()


def load_json_dict(filepath: str) -> dict:
    """Load a JSON dict file. Returns empty dict on missing/corrupt file."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning(f"Failed to load existing data from {filepath}: {e}")
    return {}


def load_resume_meta(filepath: str) -> dict:
    """Load resume metadata (last_page, etc.) from a sidecar .meta.json file."""
    meta_path = filepath + ".meta.json"
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, KeyError):
        return {}


def save_resume_meta(filepath: str, meta: dict):
    """Save resume metadata to a sidecar .meta.json file."""
    meta_path = filepath + ".meta.json"
    atomic_json_write(meta, meta_path)


def clear_resume_meta(filepath: str):
    """Remove the sidecar .meta.json file after successful completion."""
    meta_path = filepath + ".meta.json"
    try:
        os.unlink(meta_path)
    except OSError:
        pass
