"""Shared utilities for video_fetch_yjf.

Provides configuration loading (YAML with a built-in minimal fallback parser),
logging setup, environment variable resolution, and security helpers
(domain whitelist / MIME checks).
"""
from __future__ import annotations

import os
import re
import sys
import logging
from pathlib import Path
from typing import Any, Dict

SKILL_ROOT = Path(__file__).resolve().parent.parent

# 默认配置：**优先用户实际配置** `config/config.yaml`，不存在才回退到示例。
# （此前恒指 example，导致用户改了 config.yaml 却完全不生效——所有不带
#  `--config` 的运行都在读示例，Obsidian/ima 等配置形同虚设。）
_USER_CONFIG = SKILL_ROOT / "config" / "config.yaml"
DEFAULT_CONFIG = _USER_CONFIG if _USER_CONFIG.exists() else SKILL_ROOT / "config" / "config.example.yaml"

LOG = logging.getLogger("video_fetch_yjf")


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


# --------------------------------------------------------------------------- #
# Environment resolution
# --------------------------------------------------------------------------- #
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def resolve_env(value: Any, required: bool = False, name: str = "") -> Any:
    """Replace ${VAR} placeholders with environment variables.

    Returns the (possibly) transformed value. When ``required`` is True and the
    resolved value is empty, logs a warning (used for secrets).
    """
    if not isinstance(value, str):
        return value

    def _sub(m: "re.Match[str]") -> str:
        return os.environ.get(m.group(1), "")

    resolved = _ENV_PATTERN.sub(_sub, value)
    if required and not resolved:
        LOG.warning("Required environment variable placeholder unresolved: %s", name or value)
    return resolved


# --------------------------------------------------------------------------- #
# Minimal YAML loader (fallback when PyYAML is unavailable)
# --------------------------------------------------------------------------- #
def _coerce(scalar: str) -> Any:
    s = scalar.strip()
    if s == "" or s in ("~", "null", "None"):
        return None
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _mini_yaml_load(text: str) -> Dict[str, Any]:
    """Parse a restricted YAML subset: nested maps, block lists, scalars."""
    root: Dict[str, Any] = {}
    stack = [(-1, root)]  # (indent, container)

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()

        # list item
        if content.startswith("- "):
            item = _coerce(content[2:])
            parent_indent, parent = stack[-1]
            if not isinstance(parent, list):
                # create list anchored to parent map under previous key
                pass
            parent.append(item)  # type: ignore[union-attr]
            continue

        if ":" not in content:
            continue
        key, _, val = content.partition(":")
        key = key.strip()
        val = val.strip()

        # pop stack to correct indent
        while stack and stack[-1][0] >= indent and len(stack) > 1:
            stack.pop()
        parent_indent, parent = stack[-1]

        if val == "":
            # new mapping (or list) begins on following indented lines
            child: Dict[str, Any] = {}
            parent[key] = child  # type: ignore[index]
            stack.append((indent, child))
        else:
            parent[key] = _coerce(val)  # type: ignore[index]
    return root


def load_config(path: str | os.PathLike | None = None) -> Dict[str, Any]:
    """Load YAML config, resolving ${ENV} placeholders recursively."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path}")

    text = cfg_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
    except Exception:
        LOG.debug("PyYAML unavailable, using minimal fallback parser")
        data = _mini_yaml_load(text)

    return _resolve_tree(data)


def _resolve_tree(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _resolve_tree(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_tree(v) for v in node]
    if isinstance(node, str):
        return resolve_env(node)
    return node


# --------------------------------------------------------------------------- #
# Security helpers
# --------------------------------------------------------------------------- #
def is_domain_allowed(url: str, whitelist: list[str] | None = None) -> bool:
    """Return True if the URL host is within the allowed domain whitelist."""
    from urllib.parse import urlparse

    if not whitelist:
        return True
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    host = host.lower()
    for dom in whitelist:
        dom = dom.lower().lstrip("*.")
        if host == dom or host.endswith("." + dom):
            return True
    return False


def safe_extract_dir(base: str | os.PathLike) -> Path:
    """Return a dedicated temp directory under base for isolation."""
    p = Path(base) / ".cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


# --------------------------------------------------------------------------- #
# Tool PATH bootstrap (ffmpeg / yt-dlp discovery)
# --------------------------------------------------------------------------- #
def ensure_tools_on_path() -> None:
    """Prepend known tool bin dirs to PATH so ffmpeg/yt-dlp are discoverable
    by subprocess calls regardless of the user's shell PATH.

    ffmpeg/ffprobe are placed in the isolated venv's Scripts dir (same place
    yt-dlp lives), so we add that dir. An optional isolated binaries dir is
    also supported if present.
    """
    candidates = []
    exe = sys.executable
    if exe:
        candidates.append(os.path.dirname(exe))  # venv Scripts dir（跨平台，首选）
    # 兜底目录由 HOME 推导，避免写死某台机器的绝对路径；
    # 另可用 VIDEO_FETCH_TOOL_BIN 追加任意目录（os.pathsep 分隔）。
    candidates.append(str(Path.home() / ".workbuddy" / "binaries" / "ffmpeg" / "bin"))
    for extra in os.environ.get("VIDEO_FETCH_TOOL_BIN", "").split(os.pathsep):
        if extra:
            candidates.append(extra)
    existing = os.environ.get("PATH", "").split(os.pathsep)
    changed = False
    for c in candidates:
        if c and os.path.isdir(c) and c not in existing:
            existing.insert(0, c)
            changed = True
    if changed:
        os.environ["PATH"] = os.pathsep.join(existing)


# Ensure tool binaries are discoverable as early as possible.
ensure_tools_on_path()
