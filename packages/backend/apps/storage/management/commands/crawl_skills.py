"""Management command to crawl GitHub skill repos and populate the SkillCatalogEntry table."""

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from apps.storage.models import SkillCatalogEntry

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"


@dataclass
class SkillSource:
    """A GitHub repo that contains skills."""

    owner: str
    repo: str
    pattern: str  # "standard", "root_level", "indexed", "single"
    source_type: str  # "official", "community"
    category: str = ""  # default category for skills from this repo
    skill_dir: str = "skills"  # subdir name for "standard" pattern


# ── Curated source list ──────────────────────────────────────────────────────
# Each entry is a known repo with a known structure. We don't dynamically
# parse READMEs or follow link aggregators — too fragile.
SKILL_SOURCES: list[SkillSource] = [
    # Official collections
    SkillSource("anthropics", "skills", "standard", "official", "documents"),
    SkillSource("huggingface", "skills", "standard", "official", "ai-ml"),
    # Community collections
    SkillSource("skillcreatorai", "Ai-Agent-Skills", "indexed", "community"),
    SkillSource(
        "shajith003", "awesome-claude-skills", "root_level", "community", "development"
    ),
    SkillSource("hikanner", "agent-skills", "root_level", "community", "development"),
    SkillSource("chadboyda", "agent-gtm-skills", "standard", "community", "marketing"),
    SkillSource(
        "product-on-purpose", "pm-skills", "standard", "community", "product-management"
    ),
    SkillSource("sanjay3290", "ai-skills", "standard", "community", "integration"),
    SkillSource("GuDaStudio", "skills", "standard", "community", "collaboration"),
    SkillSource(
        "mhattingpete",
        "claude-skills-marketplace",
        "root_level",
        "community",
        "development",
    ),
    SkillSource("kukapay", "crypto-skills", "standard", "community", "web3"),
    # Individual skill repos (single SKILL.md)
    SkillSource("zxkane", "aws-skills", "single", "community", "development"),
    SkillSource(
        "chrisvoncsefalvay", "claude-d3js-skill", "single", "community", "data-analysis"
    ),
    SkillSource("lackeyjb", "playwright-skill", "single", "community", "development"),
    SkillSource("smerchek", "claude-epub-skill", "single", "community", "documents"),
    SkillSource("rickygao", "specrate", "single", "community", "development"),
    SkillSource(
        "conorluddy", "ios-simulator-skill", "single", "community", "development"
    ),
    SkillSource(
        "gapmiss", "obsidian-plugin-skill", "single", "community", "development"
    ),
    SkillSource(
        "coffeefuelbump",
        "csv-data-summarizer-claude-skill",
        "single",
        "community",
        "data-analysis",
    ),
    SkillSource("shepsci", "kaggle-skill", "single", "community", "data-analysis"),
    SkillSource(
        "jthack",
        "threat-hunting-with-sigma-rules-skill",
        "single",
        "community",
        "security",
    ),
    SkillSource(
        "grittygrease", "safe-encryption-skill", "single", "community", "security"
    ),
    SkillSource(
        "muratcankoylan",
        "Agent-Skills-for-Context-Engineering",
        "single",
        "community",
        "advanced",
    ),
    SkillSource("jakedahn", "pomodoro", "single", "community", "workflow"),
    SkillSource("gmickel", "sheets-cli", "single", "community", "integration"),
    SkillSource("fabioc-aloha", "spotify-skill", "single", "community", "integration"),
    SkillSource("caopulan", "Notification-Skill", "single", "community", "integration"),
    SkillSource("frmoretto", "stream-coding", "single", "community", "development"),
    SkillSource("knot0-com", "vibe-testing", "single", "community", "development"),
    SkillSource(
        "kylehughes",
        "the-unofficial-swift-concurrency-migration-skill",
        "single",
        "community",
        "development",
    ),
]

# Category display names
CATEGORY_LABELS = {
    "documents": "Documents",
    "development": "Development",
    "data-analysis": "Data & Analysis",
    "integration": "Integration",
    "security": "Security",
    "ai-ml": "AI & ML",
    "marketing": "Marketing",
    "product-management": "Product Management",
    "collaboration": "Collaboration",
    "web3": "Web3",
    "workflow": "Workflow",
    "advanced": "Advanced",
}

# Category icons
CATEGORY_ICONS = {
    "documents": "📄",
    "development": "💻",
    "data-analysis": "📊",
    "integration": "🔗",
    "security": "🔐",
    "ai-ml": "🤖",
    "marketing": "📈",
    "product-management": "📋",
    "collaboration": "🤝",
    "web3": "⛓️",
    "workflow": "⚡",
    "advanced": "🧪",
}


# ── Limits for skill file collection ─────────────────────────────────────────
MAX_FILES_PER_SKILL = 100
MAX_FILE_SIZE_BYTES = 512_000  # 512KB per file
MAX_TOTAL_SIZE_BYTES = 10_000_000  # 10MB total per skill

BINARY_EXTENSIONS = frozenset(
    {
        ".ttf",
        ".woff",
        ".woff2",
        ".eot",
        ".otf",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".svg",
        ".webp",
        ".mp3",
        ".mp4",
        ".wav",
        ".ogg",
        ".webm",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".wasm",
        ".pyc",
        ".pyo",
        ".so",
        ".dll",
        ".dylib",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
    }
)

SKIP_DIRS = frozenset(
    {
        "node_modules",
        "__pycache__",
        ".git",
        "dist",
        "build",
        ".venv",
        "venv",
    }
)


def extract_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML front-matter from a SKILL.md file.

    Compatible with exo's extract_front_matter but standalone.
    Returns (metadata_dict, body_markdown).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end < 0:
        return {}, text

    meta: dict[str, Any] = {}
    current_key = None
    for line in lines[1:end]:
        colon = line.find(":")
        if colon < 0:
            # Could be a continuation of a multiline value
            if current_key and line.strip():
                meta[current_key] = meta.get(current_key, "") + " " + line.strip()
            continue
        key = line[:colon].strip().lower()
        val = line[colon + 1 :].strip()

        if key == "tool_list":
            try:
                meta[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                meta[key] = {}
        elif key == "active":
            meta[key] = val.lower() == "true"
        elif key == "metadata":
            meta[key] = {}
        else:
            # Strip surrounding quotes
            if val and val[0] in ('"', "'") and val[-1] == val[0]:
                val = val[1:-1]
            meta[key] = val
        current_key = key

    body = "\n".join(lines[end + 1 :]).strip()
    return meta, body


class GitHubSkillCrawler:
    """Crawls GitHub repos for SKILL.md files using the GitHub API."""

    def __init__(
        self, client: httpx.Client, dry_run: bool = False, collect_files: bool = False
    ):
        self.client = client
        self.dry_run = dry_run
        self.collect_files = collect_files
        self.stats = {"added": 0, "updated": 0, "skipped": 0, "failed": 0}

    def _get_json(self, url: str) -> Any:
        """Fetch JSON from GitHub API with error handling."""
        resp = self.client.get(url)
        if resp.status_code == 403:
            logger.warning("GitHub API rate limit hit")
            raise RuntimeError("GitHub API rate limit exceeded")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def _get_raw(
        self, owner: str, repo: str, path: str, branch: str = "main"
    ) -> str | None:
        """Fetch raw file content from GitHub."""
        url = f"{GITHUB_RAW}/{owner}/{repo}/{branch}/{path}"
        resp = self.client.get(url)
        if resp.status_code == 404:
            # Try 'master' branch
            url = f"{GITHUB_RAW}/{owner}/{repo}/master/{path}"
            resp = self.client.get(url)
            if resp.status_code == 404:
                return None
        resp.raise_for_status()
        return resp.text

    def _find_skill_md(self, owner: str, repo: str, dir_path: str) -> str | None:
        """Try to fetch SKILL.md or skill.md from a directory."""
        for filename in ("SKILL.md", "skill.md"):
            path = f"{dir_path}/{filename}" if dir_path else filename
            content = self._get_raw(owner, repo, path)
            if content:
                return content
        return None

    def _detect_supporting_files(self, contents: list[dict]) -> tuple[bool, bool]:
        """Check if a skill directory has scripts/ or templates/ subdirs."""
        names = {item["name"].lower() for item in contents if item["type"] == "dir"}
        return "scripts" in names, "templates" in names or "references" in names

    def _collect_skill_files(
        self, owner: str, repo: str, base_path: str, contents: list[dict]
    ) -> dict[str, str]:
        """Recursively collect all text files in a skill directory.

        Returns dict mapping relative paths (from skill root) to text content.
        Skips SKILL.md (stored separately), binary files, and oversized files.
        Best-effort: returns whatever was collected if an error occurs.
        """
        files: dict[str, str] = {}
        total_size = [0]  # mutable ref for recursive tracking
        try:
            self._collect_files_recursive(
                owner, repo, base_path, base_path, contents, files, total_size
            )
        except Exception as e:
            logger.debug(
                f"    File collection interrupted ({len(files)} files collected): {e}"
            )
        return files

    def _collect_files_recursive(
        self,
        owner: str,
        repo: str,
        base_path: str,
        current_path: str,
        contents: list[dict],
        files: dict[str, str],
        total_size: list[int],
    ) -> None:
        """Recursive helper for _collect_skill_files."""
        for item in contents:
            if len(files) >= MAX_FILES_PER_SKILL:
                return

            name = item["name"]

            try:
                if item["type"] == "file":
                    # Skip SKILL.md (stored separately) and binary files
                    if name.lower() in ("skill.md",):
                        continue
                    ext = os.path.splitext(name)[1].lower()
                    if ext in BINARY_EXTENSIONS:
                        continue
                    size = item.get("size", 0)
                    if size > MAX_FILE_SIZE_BYTES:
                        logger.debug(
                            f"    Skipping oversized file: {name} ({size} bytes)"
                        )
                        continue
                    if total_size[0] + size > MAX_TOTAL_SIZE_BYTES:
                        logger.debug(
                            f"    Total size limit reached, skipping remaining files"
                        )
                        return

                    file_path = f"{current_path}/{name}" if current_path else name
                    content = self._get_raw(owner, repo, file_path)
                    if content is not None:
                        rel_path = (
                            file_path[len(base_path) + 1 :] if base_path else file_path
                        )
                        files[rel_path] = content
                        total_size[0] += len(content.encode("utf-8"))

                elif item["type"] == "dir":
                    if name.startswith(".") or name.lower() in SKIP_DIRS:
                        continue
                    subdir_path = f"{current_path}/{name}" if current_path else name
                    subdir_contents = self._get_json(
                        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{subdir_path}"
                    )
                    if subdir_contents:
                        self._collect_files_recursive(
                            owner,
                            repo,
                            base_path,
                            subdir_path,
                            subdir_contents,
                            files,
                            total_size,
                        )
            except Exception as e:
                logger.debug(f"    Skipping {name}: {e}")
                continue

    def _make_slug(self, name: str, source: SkillSource) -> str:
        """Generate a unique slug from skill name."""
        slug = slugify(name)
        if not slug:
            slug = slugify(f"{source.owner}-{source.repo}")
        return slug

    def _upsert_skill(
        self,
        slug: str,
        name: str,
        description: str,
        content: str,
        source: SkillSource,
        source_path: str,
        has_scripts: bool = False,
        has_templates: bool = False,
        skill_files: dict[str, str] | None = None,
        meta: dict | None = None,
    ) -> None:
        """Create or update a SkillCatalogEntry."""
        meta = meta or {}
        category = meta.get("category", source.category) or "development"
        # Normalize category
        if category not in CATEGORY_LABELS:
            category = source.category or "development"

        author = meta.get("author", "") or meta.get("source", "") or source.owner
        icon = CATEGORY_ICONS.get(category, "📦")

        if self.dry_run:
            logger.info(f"  [DRY RUN] Would upsert: {slug} ({name})")
            self.stats["added"] += 1
            return

        _, created = SkillCatalogEntry.objects.update_or_create(
            slug=slug,
            defaults={
                "name": name,
                "description": description[:1000] if description else "",
                "category": category,
                "source_type": source.source_type,
                "source_repo": f"{source.owner}/{source.repo}",
                "source_path": source_path,
                "author": author[:128] if author else "",
                "skill_md_content": content,
                "has_scripts": has_scripts,
                "has_templates": has_templates,
                "skill_files": skill_files or {},
                "tags": meta.get("tags", []),
                "license": (meta.get("license", "") or "")[:64],
                "version": (meta.get("version", "") or "")[:32],
                "icon": icon,
            },
        )
        if created:
            self.stats["added"] += 1
            logger.info(f"  + Added: {slug}")
        else:
            self.stats["updated"] += 1
            logger.info(f"  ~ Updated: {slug}")

    def crawl_source(self, source: SkillSource) -> None:
        """Crawl a single source based on its pattern."""
        logger.info(f"Crawling {source.owner}/{source.repo} (pattern={source.pattern})")
        try:
            if source.pattern == "standard":
                self._crawl_standard(source)
            elif source.pattern == "root_level":
                self._crawl_root_level(source)
            elif source.pattern == "indexed":
                self._crawl_indexed(source)
            elif source.pattern == "single":
                self._crawl_single(source)
            else:
                logger.warning(f"  Unknown pattern: {source.pattern}")
                self.stats["failed"] += 1
        except Exception as e:
            logger.error(f"  Failed to crawl {source.owner}/{source.repo}: {e}")
            self.stats["failed"] += 1

    def _crawl_standard(self, source: SkillSource) -> None:
        """Crawl repos with skills/<name>/SKILL.md structure."""
        contents = self._get_json(
            f"{GITHUB_API}/repos/{source.owner}/{source.repo}/contents/{source.skill_dir}"
        )
        if not contents:
            logger.warning(f"  No '{source.skill_dir}/' directory found")
            self.stats["failed"] += 1
            return

        dirs = [item for item in contents if item["type"] == "dir"]
        for d in dirs:
            skill_name = d["name"]
            dir_path = f"{source.skill_dir}/{skill_name}"
            content = self._find_skill_md(source.owner, source.repo, dir_path)
            if not content:
                logger.debug(f"  No SKILL.md in {dir_path}")
                self.stats["skipped"] += 1
                continue

            meta, body = extract_front_matter(content)
            name = meta.get("name", skill_name)
            description = meta.get("description", "")
            if not description and body:
                # Extract first paragraph as description
                for line in body.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        description = line[:200]
                        break

            # Check for supporting files
            dir_contents = self._get_json(
                f"{GITHUB_API}/repos/{source.owner}/{source.repo}/contents/{dir_path}"
            )
            has_scripts, has_templates = False, False
            skill_files: dict[str, str] = {}
            if dir_contents:
                has_scripts, has_templates = self._detect_supporting_files(dir_contents)
                if self.collect_files:
                    skill_files = self._collect_skill_files(
                        source.owner, source.repo, dir_path, dir_contents
                    )

            slug = self._make_slug(name, source)
            self._upsert_skill(
                slug=slug,
                name=name,
                description=description,
                content=content,
                source=source,
                source_path=dir_path,
                has_scripts=has_scripts,
                has_templates=has_templates,
                skill_files=skill_files,
                meta=meta,
            )

    def _crawl_root_level(self, source: SkillSource) -> None:
        """Crawl repos with <name>/SKILL.md at the repo root."""
        contents = self._get_json(
            f"{GITHUB_API}/repos/{source.owner}/{source.repo}/contents/"
        )
        if not contents:
            logger.warning(f"  Could not list repo root")
            self.stats["failed"] += 1
            return

        dirs = [
            item
            for item in contents
            if item["type"] == "dir"
            and not item["name"].startswith(".")
            and item["name"] not in ("node_modules", "dist", "site", "docs", ".github")
        ]

        for d in dirs:
            skill_name = d["name"]
            content = self._find_skill_md(source.owner, source.repo, skill_name)
            if not content:
                self.stats["skipped"] += 1
                continue

            meta, body = extract_front_matter(content)
            name = meta.get("name", skill_name)
            description = meta.get("description", "")
            if not description and body:
                for line in body.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        description = line[:200]
                        break

            dir_contents = self._get_json(
                f"{GITHUB_API}/repos/{source.owner}/{source.repo}/contents/{skill_name}"
            )
            has_scripts, has_templates = False, False
            skill_files: dict[str, str] = {}
            if dir_contents:
                has_scripts, has_templates = self._detect_supporting_files(dir_contents)
                if self.collect_files:
                    skill_files = self._collect_skill_files(
                        source.owner, source.repo, skill_name, dir_contents
                    )

            slug = self._make_slug(name, source)
            self._upsert_skill(
                slug=slug,
                name=name,
                description=description,
                content=content,
                source=source,
                source_path=skill_name,
                has_scripts=has_scripts,
                has_templates=has_templates,
                skill_files=skill_files,
                meta=meta,
            )

    def _crawl_indexed(self, source: SkillSource) -> None:
        """Crawl repos with a skills.json index file."""
        index_content = self._get_raw(source.owner, source.repo, "skills.json")
        if not index_content:
            # Fall back to standard crawl
            logger.info(f"  No skills.json found, falling back to standard crawl")
            self._crawl_standard(source)
            return

        try:
            index = json.loads(index_content)
        except json.JSONDecodeError:
            logger.warning(f"  Invalid skills.json")
            self._crawl_standard(source)
            return

        # skillcreatorai format: {"skills": [{"name": "...", "description": "...", ...}]}
        skills_list = index.get("skills", [])
        if not skills_list:
            self._crawl_standard(source)
            return

        for skill_info in skills_list:
            skill_name = skill_info.get("name", "")
            if not skill_name:
                continue

            dir_path = f"skills/{skill_name}"
            content = self._find_skill_md(source.owner, source.repo, dir_path)
            if not content:
                self.stats["skipped"] += 1
                continue

            meta, body = extract_front_matter(content)
            name = meta.get("name", skill_name)
            description = meta.get("description", "") or skill_info.get(
                "description", ""
            )
            if not description and body:
                for line in body.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("#"):
                        description = line[:200]
                        break

            # Collect supporting files
            has_scripts, has_templates = False, False
            skill_files: dict[str, str] = {}
            if self.collect_files:
                dir_contents = self._get_json(
                    f"{GITHUB_API}/repos/{source.owner}/{source.repo}/contents/{dir_path}"
                )
                if dir_contents:
                    has_scripts, has_templates = self._detect_supporting_files(
                        dir_contents
                    )
                    skill_files = self._collect_skill_files(
                        source.owner, source.repo, dir_path, dir_contents
                    )

            # Merge index metadata with front-matter
            merged_meta = {**skill_info, **meta}
            slug = self._make_slug(name, source)
            self._upsert_skill(
                slug=slug,
                name=name,
                description=description,
                content=content,
                source=source,
                source_path=dir_path,
                has_scripts=has_scripts,
                has_templates=has_templates,
                skill_files=skill_files,
                meta=merged_meta,
            )

    def _crawl_single(self, source: SkillSource) -> None:
        """Crawl repos with a single skill (SKILL.md at root or in a subdir)."""
        # Try root first
        content = self._find_skill_md(source.owner, source.repo, "")
        source_path = ""

        if not content:
            # Try common subdirectories
            for subdir in ("skill", "skills", source.repo):
                content = self._find_skill_md(source.owner, source.repo, subdir)
                if content:
                    source_path = subdir
                    break

        if not content:
            logger.warning(f"  No SKILL.md found in {source.owner}/{source.repo}")
            self.stats["failed"] += 1
            return

        meta, body = extract_front_matter(content)
        name = meta.get("name", source.repo)
        description = meta.get("description", "")
        if not description and body:
            for line in body.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    description = line[:200]
                    break

        # Check root for supporting files
        root_contents = self._get_json(
            f"{GITHUB_API}/repos/{source.owner}/{source.repo}/contents/"
        )
        has_scripts, has_templates = False, False
        skill_files: dict[str, str] = {}
        if root_contents:
            has_scripts, has_templates = self._detect_supporting_files(root_contents)
            if self.collect_files:
                scan_path = source_path or ""
                scan_contents = root_contents
                if source_path:
                    scan_contents = (
                        self._get_json(
                            f"{GITHUB_API}/repos/{source.owner}/{source.repo}/contents/{source_path}"
                        )
                        or []
                    )
                skill_files = self._collect_skill_files(
                    source.owner, source.repo, scan_path, scan_contents
                )

        slug = self._make_slug(name, source)
        self._upsert_skill(
            slug=slug,
            name=name,
            description=description,
            content=content,
            source=source,
            source_path=source_path,
            has_scripts=has_scripts,
            has_templates=has_templates,
            skill_files=skill_files,
            meta=meta,
        )


class Command(BaseCommand):
    """Crawl GitHub skill repos and populate the SkillCatalogEntry table."""

    help = "Crawl GitHub skill repos and populate the skills marketplace catalog"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report without writing to database",
        )
        parser.add_argument(
            "--repo",
            type=str,
            help="Crawl only a specific repo (format: owner/repo)",
        )
        parser.add_argument(
            "--with-files",
            action="store_true",
            help="Also download supporting files (scripts, templates, etc.) for each skill",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        target_repo = options.get("repo")
        collect_files = options["with_files"]

        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "midsphere-skill-crawler",
        }
        # Use GITHUB_TOKEN env var for authenticated requests (5000 req/hour)
        gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if gh_token:
            headers["Authorization"] = f"Bearer {gh_token}"
            self.stdout.write("Using authenticated GitHub API (5000 req/hour)")
        else:
            self.stdout.write(
                "No GITHUB_TOKEN set — using unauthenticated API (60 req/hour). "
                "Set GITHUB_TOKEN or GH_TOKEN for higher limits."
            )

        with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
            crawler = GitHubSkillCrawler(
                client, dry_run=dry_run, collect_files=collect_files
            )

            sources = SKILL_SOURCES
            if target_repo:
                owner, repo = target_repo.split("/")
                sources = [s for s in sources if s.owner == owner and s.repo == repo]
                if not sources:
                    self.stderr.write(f"No configured source for {target_repo}")
                    return

            for source in sources:
                crawler.crawl_source(source)

            stats = crawler.stats
            mode = "[DRY RUN] " if dry_run else ""
            self.stdout.write(
                f"\n{mode}Crawl complete: "
                f"{stats['added']} added, "
                f"{stats['updated']} updated, "
                f"{stats['skipped']} skipped, "
                f"{stats['failed']} failed"
            )
            if not dry_run:
                self.stdout.write(
                    f"Total skills in catalog: {SkillCatalogEntry.objects.count()}"
                )
