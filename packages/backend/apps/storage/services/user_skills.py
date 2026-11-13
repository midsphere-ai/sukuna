"""Service layer for user-authored skills.

Handles the four create flows: in-UI editor, SKILL.md upload, .zip bundle upload,
GitHub URL import. Reuses ``extract_front_matter`` from the marketplace crawler
so user uploads share the same parser as crawled content.
"""

from __future__ import annotations

import io
import logging
import os
import re
import zipfile
from typing import Any

import httpx
from django.utils.text import slugify

from apps.storage.management.commands.crawl_skills import (
    BINARY_EXTENSIONS,
    GITHUB_API,
    GITHUB_RAW,
    SKIP_DIRS,
    extract_front_matter,
)
from apps.storage.models import UserSkill
from apps.users.models import User
from config.errors.common import InvalidInputError, NotFoundError

logger = logging.getLogger(__name__)


# ── Limits ───────────────────────────────────────────────────────────────────
MAX_SKILL_MD_BYTES = 512_000  # 512KB
MAX_FILE_BYTES = 512_000  # 512KB per supporting file
MAX_TOTAL_SUPPORTING_BYTES = 2_000_000  # 2MB combined
MAX_SUPPORTING_FILES = 100

TEXT_EXTENSIONS = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".py",
        ".sh",
        ".bash",
        ".zsh",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".html",
        ".htm",
        ".css",
        ".js",
        ".mjs",
        ".ts",
        ".tsx",
        ".jsx",
        ".xml",
        ".svg",
        ".csv",
        ".tsv",
        ".sql",
        ".rb",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".swift",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".lua",
    }
)


# ── Public API ───────────────────────────────────────────────────────────────


def parse_skill_md(text: str) -> tuple[dict[str, Any], str]:
    """Reuses the crawler's front-matter parser."""
    return extract_front_matter(text)


def build_from_editor(
    owner: User,
    *,
    name: str,
    description: str,
    body: str,
    category: str = "",
    icon: str = "",
    skill_files: dict[str, str] | None = None,
) -> UserSkill:
    """Create a UserSkill from in-UI editor fields.

    Assembles SKILL.md with YAML front-matter from the form fields and stores
    the raw body as ``skill_md_content`` (with front-matter prepended so the
    resulting file round-trips correctly when written to the sandbox).
    """
    name = (name or "").strip()
    description = (description or "").strip()
    body = (body or "").strip()
    if not name:
        raise InvalidInputError("Skill name is required.")
    if not description:
        raise InvalidInputError("Skill description is required.")
    if not body:
        raise InvalidInputError("Skill body is required.")

    slug = _unique_slug(owner, name)
    skill_md = _assemble_skill_md(
        name=name, description=description, body=body, category=category
    )
    _validate_size(skill_md.encode("utf-8"), "SKILL.md content")
    normalized_files = _normalize_skill_files(skill_files or {})

    return UserSkill.objects.create(
        owner=owner,
        slug=slug,
        name=name,
        description=description,
        category=category,
        icon=icon,
        skill_md_content=skill_md,
        skill_files=normalized_files,
        source=UserSkill.Source.EDITOR,
    )


def build_from_skill_md(
    owner: User,
    *,
    file_bytes: bytes,
    filename: str = "SKILL.md",
) -> UserSkill:
    """Create a UserSkill from an uploaded single SKILL.md file."""
    _validate_size(file_bytes, filename)
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise InvalidInputError(f"SKILL.md must be UTF-8 text: {e}") from e

    meta, _body = parse_skill_md(text)
    name = (meta.get("name") or "").strip()
    description = (meta.get("description") or "").strip()
    if not name or not description:
        raise InvalidInputError(
            "SKILL.md front-matter must include 'name' and 'description'."
        )

    slug = _unique_slug(owner, name)
    return UserSkill.objects.create(
        owner=owner,
        slug=slug,
        name=name,
        description=description,
        category=(meta.get("category") or "").strip(),
        icon=(meta.get("icon") or "").strip()[:8],
        version=(meta.get("version") or "").strip()[:32],
        skill_md_content=text,
        skill_files={},
        source=UserSkill.Source.UPLOAD_MD,
    )


def build_from_zip(
    owner: User,
    *,
    file_bytes: bytes,
    filename: str = "skill.zip",
) -> UserSkill:
    """Create a UserSkill from an uploaded .zip bundle.

    Accepts a zip containing a SKILL.md at the root or at the root of a single
    top-level directory. Collects sibling text files into ``skill_files`` as
    relative paths.
    """
    if len(file_bytes) > MAX_TOTAL_SUPPORTING_BYTES + MAX_SKILL_MD_BYTES:
        raise InvalidInputError(
            f"Zip bundle too large (max {MAX_TOTAL_SUPPORTING_BYTES + MAX_SKILL_MD_BYTES} bytes)."
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile as e:
        raise InvalidInputError(f"Invalid zip file: {e}") from e

    members = [m for m in zf.namelist() if not m.endswith("/")]
    if not members:
        raise InvalidInputError("Zip bundle is empty.")

    # Find SKILL.md; accept root-level or a single top-level directory
    skill_md_member = None
    base_prefix = ""
    for m in members:
        basename = os.path.basename(m)
        if basename.lower() in ("skill.md",):
            skill_md_member = m
            base_prefix = m[: -len(basename)]
            break

    if skill_md_member is None:
        raise InvalidInputError("Zip bundle must contain a SKILL.md file.")

    with zf.open(skill_md_member) as fh:
        skill_md_bytes = fh.read()
    _validate_size(skill_md_bytes, "SKILL.md")
    try:
        skill_md_text = skill_md_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise InvalidInputError(f"SKILL.md must be UTF-8 text: {e}") from e

    meta, _body = parse_skill_md(skill_md_text)
    name = (meta.get("name") or "").strip()
    description = (meta.get("description") or "").strip()
    if not name or not description:
        raise InvalidInputError(
            "SKILL.md front-matter must include 'name' and 'description'."
        )

    # Collect supporting files under base_prefix
    skill_files: dict[str, str] = {}
    total_size = 0
    for m in members:
        if m == skill_md_member:
            continue
        if base_prefix and not m.startswith(base_prefix):
            continue
        rel_path = m[len(base_prefix) :] if base_prefix else m
        if not rel_path or rel_path.endswith("/"):
            continue
        # Skip hidden/build dirs
        parts = rel_path.split("/")
        if any(p.startswith(".") or p in SKIP_DIRS for p in parts[:-1]):
            continue

        ext = os.path.splitext(rel_path)[1].lower()
        if ext in BINARY_EXTENSIONS:
            continue
        if ext and ext not in TEXT_EXTENSIONS:
            # Unknown extension — skip defensively
            continue

        info = zf.getinfo(m)
        if info.file_size > MAX_FILE_BYTES:
            logger.debug(
                "Skipping oversized file %s (%d bytes)", rel_path, info.file_size
            )
            continue
        if total_size + info.file_size > MAX_TOTAL_SUPPORTING_BYTES:
            logger.debug("Total supporting-files limit reached")
            break
        if len(skill_files) >= MAX_SUPPORTING_FILES:
            break

        with zf.open(m) as fh:
            try:
                content = fh.read().decode("utf-8")
            except UnicodeDecodeError:
                continue
        skill_files[rel_path] = content
        total_size += len(content.encode("utf-8"))

    slug = _unique_slug(owner, name)
    return UserSkill.objects.create(
        owner=owner,
        slug=slug,
        name=name,
        description=description,
        category=(meta.get("category") or "").strip(),
        icon=(meta.get("icon") or "").strip()[:8],
        version=(meta.get("version") or "").strip()[:32],
        skill_md_content=skill_md_text,
        skill_files=skill_files,
        source=UserSkill.Source.UPLOAD_ZIP,
    )


_GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)"
    r"(?:/tree/(?P<branch>[\w.-]+)(?:/(?P<path>.+))?)?/?$"
)


def build_from_github(owner: User, *, url: str) -> UserSkill:
    """Create a UserSkill by fetching a SKILL.md bundle from a public GitHub URL.

    Accepts URLs like:
      - https://github.com/{org}/{repo}                       (SKILL.md at root)
      - https://github.com/{org}/{repo}/tree/{branch}         (SKILL.md at root)
      - https://github.com/{org}/{repo}/tree/{branch}/{path}  (SKILL.md in subdir)
    """
    url = (url or "").strip()
    match = _GITHUB_URL_RE.match(url)
    if not match:
        raise InvalidInputError("URL must be a public github.com repository URL.")

    gh_owner = match.group("owner")
    gh_repo = match.group("repo")
    gh_branch = match.group("branch") or "main"
    gh_path = (match.group("path") or "").strip("/")

    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    with httpx.Client(headers=headers, timeout=20.0) as client:
        skill_md_text, collected_path = _github_fetch_skill_md(
            client, gh_owner, gh_repo, gh_branch, gh_path
        )
        if skill_md_text is None:
            raise NotFoundError(
                "SKILL.md not found at that URL. Point to the directory or repo "
                "that contains SKILL.md."
            )

        _validate_size(skill_md_text.encode("utf-8"), "SKILL.md")
        meta, _body = parse_skill_md(skill_md_text)
        name = (meta.get("name") or "").strip()
        description = (meta.get("description") or "").strip()
        if not name or not description:
            raise InvalidInputError(
                "SKILL.md front-matter must include 'name' and 'description'."
            )

        skill_files = _github_collect_supporting_files(
            client, gh_owner, gh_repo, gh_branch, collected_path
        )

    slug = _unique_slug(owner, name)
    return UserSkill.objects.create(
        owner=owner,
        slug=slug,
        name=name,
        description=description,
        category=(meta.get("category") or "").strip(),
        icon=(meta.get("icon") or "").strip()[:8],
        version=(meta.get("version") or "").strip()[:32],
        skill_md_content=skill_md_text,
        skill_files=skill_files,
        source=UserSkill.Source.GITHUB,
        source_url=url,
    )


def update_skill(
    skill: UserSkill,
    *,
    name: str | None = None,
    description: str | None = None,
    body: str | None = None,
    category: str | None = None,
    icon: str | None = None,
    skill_files: dict[str, str] | None = None,
) -> UserSkill:
    """Partial update for editor-sourced skills.

    For non-editor sources we still allow metadata updates, but body edits
    re-assemble SKILL.md only when a body is provided.
    """
    if name is not None:
        name = name.strip()
        if not name:
            raise InvalidInputError("Skill name cannot be empty.")
        skill.name = name
    if description is not None:
        description = description.strip()
        if not description:
            raise InvalidInputError("Skill description cannot be empty.")
        skill.description = description
    if category is not None:
        skill.category = category.strip()
    if icon is not None:
        skill.icon = icon.strip()[:8]

    if (
        body is not None
        or name is not None
        or description is not None
        or category is not None
    ):
        if skill.source == UserSkill.Source.EDITOR:
            new_body = (
                body if body is not None else _extract_body(skill.skill_md_content)
            )
            skill.skill_md_content = _assemble_skill_md(
                name=skill.name,
                description=skill.description,
                body=new_body,
                category=skill.category,
            )
            _validate_size(skill.skill_md_content.encode("utf-8"), "SKILL.md content")

    if skill_files is not None:
        skill.skill_files = _normalize_skill_files(skill_files)

    skill.save()
    return skill


def delete_skill(skill: UserSkill) -> None:
    skill.delete()


# ── Internals ────────────────────────────────────────────────────────────────


def _validate_size(data: bytes, what: str) -> None:
    if len(data) > MAX_SKILL_MD_BYTES:
        raise InvalidInputError(f"{what} exceeds {MAX_SKILL_MD_BYTES} byte limit.")


def _normalize_skill_files(files: dict[str, str]) -> dict[str, str]:
    """Validate, normalize, and size-check a user-provided skill_files dict."""
    if not files:
        return {}
    if len(files) > MAX_SUPPORTING_FILES:
        raise InvalidInputError(
            f"Too many supporting files (max {MAX_SUPPORTING_FILES})."
        )
    normalized: dict[str, str] = {}
    total = 0
    for raw_path, content in files.items():
        path = _sanitize_path(raw_path)
        if not path:
            continue
        if path.lower() in ("skill.md",):
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext in BINARY_EXTENSIONS:
            raise InvalidInputError(f"Binary file not allowed: {path}")
        if ext and ext not in TEXT_EXTENSIONS:
            raise InvalidInputError(f"Unsupported file type: {path}")
        if not isinstance(content, str):
            raise InvalidInputError(f"File content must be text: {path}")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            raise InvalidInputError(
                f"File '{path}' exceeds {MAX_FILE_BYTES} byte limit."
            )
        total += len(encoded)
        if total > MAX_TOTAL_SUPPORTING_BYTES:
            raise InvalidInputError(
                f"Total file content exceeds {MAX_TOTAL_SUPPORTING_BYTES} bytes."
            )
        normalized[path] = content
    return normalized


def _sanitize_path(path: str) -> str:
    """Normalize a relative path and reject escapes."""
    if not path:
        return ""
    p = path.strip().lstrip("/")
    if not p:
        return ""
    parts: list[str] = []
    for segment in p.split("/"):
        if not segment or segment == ".":
            continue
        if segment == "..":
            raise InvalidInputError("Path traversal not allowed.")
        if segment.startswith("."):
            raise InvalidInputError(f"Hidden files not allowed: {path}")
        parts.append(segment)
    if not parts:
        return ""
    return "/".join(parts)


def _assemble_skill_md(
    *, name: str, description: str, body: str, category: str = ""
) -> str:
    """Build a SKILL.md file from form fields."""
    front_matter = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]
    if category:
        front_matter.append(f"category: {category}")
    front_matter.append("---")
    return "\n".join(front_matter) + "\n\n" + body.strip() + "\n"


def _extract_body(text: str) -> str:
    """Return the body portion of a SKILL.md (after closing front-matter ---)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1 :]).strip()
    return text


def _unique_slug(owner: User, name: str) -> str:
    """Slugify name and disambiguate per-owner with a numeric suffix."""
    base = slugify(name) or "skill"
    slug = base[:128]
    counter = 2
    while UserSkill.objects.slug_exists(owner, slug):
        suffix = f"-{counter}"
        slug = (base[: 128 - len(suffix)]) + suffix
        counter += 1
        if counter > 1000:
            raise InvalidInputError("Could not generate a unique slug.")
    return slug


# ── GitHub helpers ───────────────────────────────────────────────────────────


def _github_raw(
    client: httpx.Client, owner: str, repo: str, branch: str, path: str
) -> str | None:
    url = f"{GITHUB_RAW}/{owner}/{repo}/{branch}/{path}"
    resp = client.get(url)
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        logger.warning("GitHub raw fetch failed %s: %s", url, resp.status_code)
        return None
    return resp.text


def _github_list_dir(
    client: httpx.Client, owner: str, repo: str, branch: str, path: str
) -> list[dict] | None:
    url = f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}?ref={branch}"
    resp = client.get(url)
    if resp.status_code == 404:
        return None
    if resp.status_code == 403:
        raise InvalidInputError("GitHub API rate limit hit. Try again later.")
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else None


def _github_fetch_skill_md(
    client: httpx.Client, owner: str, repo: str, branch: str, path: str
) -> tuple[str | None, str]:
    """Try to fetch SKILL.md at ``path``. Returns (content, resolved_path)."""
    candidates = []
    if path:
        candidates.append(f"{path}/SKILL.md")
        candidates.append(f"{path}/skill.md")
    else:
        candidates.append("SKILL.md")
        candidates.append("skill.md")

    for candidate in candidates:
        content = _github_raw(client, owner, repo, branch, candidate)
        if content is not None:
            # collected_path = directory that held SKILL.md
            return content, os.path.dirname(candidate)

    # Fall back to master branch
    if branch == "main":
        for candidate in candidates:
            content = _github_raw(client, owner, repo, "master", candidate)
            if content is not None:
                return content, os.path.dirname(candidate)

    return None, path


def _github_collect_supporting_files(
    client: httpx.Client, owner: str, repo: str, branch: str, dir_path: str
) -> dict[str, str]:
    """Recursively collect text files beside SKILL.md up to configured limits."""
    files: dict[str, str] = {}
    total_size = [0]

    def walk(current: str) -> None:
        if len(files) >= MAX_SUPPORTING_FILES:
            return
        try:
            contents = _github_list_dir(client, owner, repo, branch, current)
        except InvalidInputError:
            raise
        except Exception as e:  # best-effort collection
            logger.debug("github list_dir failed %s: %s", current, e)
            return
        if not contents:
            return
        for item in contents:
            if len(files) >= MAX_SUPPORTING_FILES:
                return
            name = item.get("name", "")
            if not name:
                continue
            if name.startswith(".") or name in SKIP_DIRS:
                continue
            item_type = item.get("type")
            sub = f"{current}/{name}" if current else name
            if item_type == "file":
                if name.lower() == "skill.md":
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in BINARY_EXTENSIONS:
                    continue
                if ext and ext not in TEXT_EXTENSIONS:
                    continue
                size = int(item.get("size") or 0)
                if size > MAX_FILE_BYTES:
                    continue
                if total_size[0] + size > MAX_TOTAL_SUPPORTING_BYTES:
                    return
                text = _github_raw(client, owner, repo, branch, sub)
                if text is None:
                    continue
                rel = sub[len(dir_path) + 1 :] if dir_path else sub
                files[rel] = text
                total_size[0] += len(text.encode("utf-8"))
            elif item_type == "dir":
                walk(sub)

    walk(dir_path)
    return files
