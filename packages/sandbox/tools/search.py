"""Web search and knowledge retrieval tool — multi-provider search with caching."""

__version__ = "0.2.0"

# ========================
# Standard library imports
# ========================
import asyncio
import calendar
import json
import logging
import os
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

# ========================
# Logging Configuration (MUST be before other imports)
# ========================
logging.getLogger("wikipedia").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ========================
# Third-party imports
# ========================
import requests
import wikipedia
import yaml
import yt_dlp
from _lib.utils import alias_hint, error_result, resolve_alias, success_result
from exo import tool
from pydantic import BaseModel

# ========================
# API KEYS & CONFIG
# ========================

SERPER_API_KEY = os.getenv("SERPER_API_KEY")
SERPER_BASE_URL = "https://google.serper.dev"

# Get workspace from environment
WORKSPACE = Path(os.getenv("WORKSPACE", str(Path.home()))).expanduser().resolve()
wikipedia.set_lang("en")

# MCP config for api search type
_MCP_CONFIG_PATH = Path("/tmp/.exo-mcp/mcp.json")

# Skill directories for tool search type
_BUNDLED_SKILLS_DIR = str(Path(__file__).resolve().parent.parent / "skills")
_SKILL_FILENAMES = {"skill.md", "SKILL.md"}


def _workspace_root() -> str:
    return (
        os.environ.get("PROJECT_DIR")
        or os.environ.get("WORKSPACE")
        or os.environ.get("SANDBOX_WORKSPACE_ROOT")
        or str(Path.home())
    )


def get_tool_env():
    global SERPER_API_KEY, WORKSPACE

    SERPER_API_KEY = os.getenv("SERPER_API_KEY")
    WORKSPACE = Path(os.getenv("WORKSPACE"))


class SearchResult(BaseModel):
    """Individual search result with structured data."""

    id: str
    title: str
    url: str
    snippet: str
    source: str
    display_link: str | None = None
    formatted_url: str | None = None
    image_path: str | None = None
    hint: str | None = None


def format_search_results_for_llm(results: list[SearchResult], query: str) -> str:
    if not results:
        return f"No search results found for query: '{query}'"

    formatted_parts = [f"# Search Results for: '{query}'", f"Found {len(results)} results:\n"]

    for i, result in enumerate(results, 1):
        result_section = [
            f"## Result {i}: {result.title}",
            f"**URL:** {result.url}",
            f"**Source:** {result.source}",
        ]

        if result.display_link:
            result_section.append(f"**Domain:** {result.display_link}")

        result_section.append(f"**Summary:** {result.snippet}")
        result_section.append("")

        formatted_parts.append("\n".join(result_section))

    return "\n".join(formatted_parts)


# ========================
# Serper API helpers
# ========================


def _serper_request(endpoint: str, query: str, num_results: int = 5) -> dict | None:
    """Make a POST request to the Serper API. Returns parsed JSON or None on failure."""
    if not SERPER_API_KEY:
        return None
    payload = json.dumps({"q": query, "num": num_results})
    try:
        resp = requests.post(
            f"{SERPER_BASE_URL}{endpoint}",
            data=payload,
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Serper %s request failed: %s", endpoint, exc)
        return None


def _search_serper(
    query: str,
    num_results: int = 5,
    **_kwargs,
):
    """Search the web using Serper API."""
    if not SERPER_API_KEY:
        return error_result(
            "Serper API key not configured.",
            hint="Set SERPER_API_KEY environment variable. Get a key from serper.dev.",
        )

    validated_num_results = max(1, min(10, num_results))
    data = _serper_request("/search", query, validated_num_results)
    if data is None:
        return error_result(
            "Search request failed", hint="Serper API request failed. Check SERPER_API_KEY and network connectivity."
        )

    items = data.get("organic", [])[:validated_num_results]
    search_results = []
    for i, item in enumerate(items):
        result = SearchResult(
            id=f"serper-{i}",
            title=item.get("title", ""),
            url=item.get("link", ""),
            snippet=item.get("snippet", ""),
            source="serper",
            display_link=urlparse(item.get("link", "")).netloc,
        )
        search_results.append(result)

    return success_result(
        "Search complete",
        query=query,
        results=[r.model_dump() for r in search_results],
        count=len(search_results),
    )


def _search_serper_images(
    query: str,
    num_results: int = 5,
    **_kwargs,
):
    """Search for images using Serper API and download them to the workspace."""
    if not SERPER_API_KEY:
        return error_result(
            "Serper API key not configured.",
            hint="Set SERPER_API_KEY environment variable. Get a key from serper.dev.",
        )

    validated_num_results = max(1, min(10, num_results))
    data = _serper_request("/images", query, validated_num_results)
    if data is None:
        return error_result(
            "Image search request failed",
            hint="Serper API request failed. Check SERPER_API_KEY and network connectivity.",
        )

    items = data.get("images", [])[:validated_num_results]
    dl_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
    }

    os.makedirs(f"{WORKSPACE}/google_search/", exist_ok=True)
    search_results = []
    for i, item in enumerate(items):
        img_url = item.get("imageUrl") or item.get("link", "")
        if not img_url:
            continue
        ext = os.path.splitext(urlparse(img_url).path)[1] or ".jpg"
        image_path = f"{WORKSPACE}/google_search/{uuid.uuid4()}{ext}"
        try:
            downloaded_image = requests.get(img_url, headers=dl_headers, timeout=10, stream=True)
            content_type = downloaded_image.headers.get("content-type", "")
            if "image" not in content_type.lower():
                image_path = None
            else:
                with open(image_path, "wb") as f:
                    for chunk in downloaded_image.iter_content(chunk_size=8192):
                        f.write(chunk)
        except Exception:
            image_path = None

        result = SearchResult(
            id=f"serper-image-{i}",
            title=item.get("title", ""),
            url=img_url,
            snippet=item.get("snippet", "") or item.get("title", ""),
            source="serper",
            display_link=item.get("source", ""),
            image_path=image_path,
        )
        search_results.append(result)

    return success_result(
        "Image search complete",
        query=query,
        results=[r.model_dump() for r in search_results],
        count=len(search_results),
    )


def _search_serper_news(
    query: str,
    num_results: int = 5,
    **_kwargs,
):
    """Search for news using Serper API."""
    if not SERPER_API_KEY:
        return error_result(
            "Serper API key not configured.",
            hint="Set SERPER_API_KEY environment variable. Get a key from serper.dev.",
        )

    validated_num_results = max(1, min(10, num_results))
    data = _serper_request("/news", query, validated_num_results)
    if data is None:
        return error_result(
            "News search request failed",
            hint="Serper API request failed. Check SERPER_API_KEY and network connectivity.",
        )

    items = data.get("news", [])[:validated_num_results]
    search_results = []
    for i, item in enumerate(items):
        result = SearchResult(
            id=f"serper-news-{i}",
            title=item.get("title", ""),
            url=item.get("link", ""),
            snippet=item.get("snippet", ""),
            source="serper-news",
            display_link=item.get("source", ""),
        )
        search_results.append(result)

    return success_result(
        "News search complete",
        query=query,
        results=[r.model_dump() for r in search_results],
        count=len(search_results),
    )


def _search_serper_scholar(
    query: str,
    num_results: int = 5,
    **_kwargs,
):
    """Search for academic/research papers using Serper Scholar API."""
    if not SERPER_API_KEY:
        return error_result(
            "Serper API key not configured.",
            hint="Set SERPER_API_KEY environment variable. Get a key from serper.dev.",
        )

    validated_num_results = max(1, min(10, num_results))
    data = _serper_request("/scholar", query, validated_num_results)
    if data is None:
        return error_result(
            "Scholar search request failed",
            hint="Serper API request failed. Check SERPER_API_KEY and network connectivity.",
        )

    items = data.get("organic", [])[:validated_num_results]
    search_results = []
    for i, item in enumerate(items):
        result = SearchResult(
            id=f"serper-scholar-{i}",
            title=item.get("title", ""),
            url=item.get("link", ""),
            snippet=item.get("snippet", ""),
            source="serper-scholar",
            display_link=item.get("source", "") or urlparse(item.get("link", "")).netloc,
        )
        search_results.append(result)

    return success_result(
        "Research search complete",
        query=query,
        results=[r.model_dump() for r in search_results],
        count=len(search_results),
    )


# ========================
# Platform search: api (MCP servers + addons)
# ========================


def _list_mcp_servers() -> list[dict[str, Any]]:
    """List MCP servers configured in the current sandbox."""
    if not _MCP_CONFIG_PATH.exists():
        return []
    try:
        config = json.loads(_MCP_CONFIG_PATH.read_text())
        servers = config.get("mcpServers", {})
        results = []
        for name, server_cfg in servers.items():
            tools_list = []
            try:
                proc = subprocess.run(
                    ["exo-mcp", "tool", "list", name, "--config", str(_MCP_CONFIG_PATH), "--json"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    tools_list = json.loads(proc.stdout)
            except Exception:
                pass
            tool_names = [t.get("name", "") for t in tools_list if isinstance(t, dict)]
            results.append(
                {
                    "name": name,
                    "command": server_cfg.get("command", ""),
                    "tools": tool_names,
                }
            )
        return results
    except Exception:
        return []


def _search_api(
    query: str,
    num_results: int = 5,
    **_kwargs,
) -> dict:
    """Search for APIs, MCP servers, and integrations.

    Priority: installed MCP servers → Serper web fallback.
    """
    query_lower = query.lower()
    results: list[SearchResult] = []

    # 1. Local MCP servers
    mcp_servers = _list_mcp_servers()
    for server in mcp_servers:
        name_lower = server["name"].lower()
        tools_str = ", ".join(server["tools"])
        if query_lower in name_lower or any(query_lower in t.lower() for t in server["tools"]):
            results.append(
                SearchResult(
                    id=f"mcp-{server['name']}",
                    title=f"MCP Server: {server['name']}",
                    url="",
                    snippet=f"Active MCP server with tools: {tools_str}"
                    if tools_str
                    else "Active MCP server (no tools enumerated)",
                    source="mcp",
                    hint=(
                        f"Use `exo-mcp tool call {server['name']} <tool> --config {_MCP_CONFIG_PATH} -j '{{...}}'` to invoke a tool. "
                        f"Use `exo-mcp tool list {server['name']} --config {_MCP_CONFIG_PATH}` to see all available tools."
                    ),
                )
            )

    # If no local match, include all MCP servers as context
    if not results and mcp_servers:
        for server in mcp_servers:
            tools_str = ", ".join(server["tools"])
            results.append(
                SearchResult(
                    id=f"mcp-{server['name']}",
                    title=f"MCP Server: {server['name']}",
                    url="",
                    snippet=f"Available tools: {tools_str}" if tools_str else "MCP server available",
                    source="mcp",
                    hint=(
                        f"Use `exo-mcp tool list {server['name']} --config {_MCP_CONFIG_PATH}` to see available tools on this server."
                    ),
                )
            )

    # 2. Web fallback via Serper
    if len(results) < num_results and SERPER_API_KEY:
        web_data = _serper_request("/search", f"{query} API", max(1, num_results - len(results)))
        if web_data:
            for i, item in enumerate(web_data.get("organic", [])):
                results.append(
                    SearchResult(
                        id=f"serper-api-{i}",
                        title=item.get("title", ""),
                        url=item.get("link", ""),
                        snippet=item.get("snippet", ""),
                        source="web",
                    )
                )

    return success_result(
        "API search complete",
        query=query,
        results=[r.model_dump() for r in results[:num_results]],
        count=min(len(results), num_results),
    )


# ========================
# Platform search: tool (skills)
# ========================


def _parse_skill_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter and return (metadata, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw_fm = text[3:end].strip()
    body = text[end + 4 :].strip()
    try:
        meta = yaml.safe_load(raw_fm) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, body


def _scan_local_skills() -> dict[str, dict[str, Any]]:
    """Scan bundled and user skill directories."""
    skills: dict[str, dict[str, Any]] = {}
    user_skills_dir = os.path.join(_workspace_root(), "skills")

    for source_dir in (_BUNDLED_SKILLS_DIR, user_skills_dir):
        root = Path(source_dir)
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            skill_file = None
            for fname in _SKILL_FILENAMES:
                candidate = child / fname
                if candidate.is_file():
                    skill_file = candidate
                    break
            if skill_file is None:
                continue
            try:
                text = skill_file.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = _parse_skill_frontmatter(text)
            name = meta.get("name") or child.name
            active = str(meta.get("active", "true")).lower() == "true"
            if not active:
                continue
            skills[name] = {
                "name": name,
                "description": meta.get("description", ""),
                "path": str(skill_file),
            }
    return skills


def _search_tool(
    query: str,
    num_results: int = 5,
    **_kwargs,
) -> dict:
    """Search for tools and skills.

    Priority: installed local skills → Serper web fallback.
    """
    query_lower = query.lower()
    results: list[SearchResult] = []

    # 1. Local installed skills
    skills = _scan_local_skills()
    for skill_name, skill_info in skills.items():
        name_lower = skill_name.lower()
        desc_lower = skill_info.get("description", "").lower()
        if query_lower in name_lower or query_lower in desc_lower:
            results.append(
                SearchResult(
                    id=f"skill-{skill_name}",
                    title=f"Skill: {skill_name}",
                    url="",
                    snippet=skill_info.get("description", ""),
                    source="installed",
                    hint=f"This skill is installed locally. Use skill(action='get', name='{skill_name}') to load its instructions and follow them for this task.",
                )
            )

    # If no match, list all skills
    if not results and skills:
        for skill_name, skill_info in list(skills.items())[:num_results]:
            results.append(
                SearchResult(
                    id=f"skill-{skill_name}",
                    title=f"Skill: {skill_name}",
                    url="",
                    snippet=skill_info.get("description", ""),
                    source="installed",
                    hint=f"Use skill(action='get', name='{skill_name}') to load this skill's instructions.",
                )
            )

    # 2. Web fallback via Serper
    if len(results) < num_results and SERPER_API_KEY:
        web_data = _serper_request("/search", f"{query} tool plugin", max(1, num_results - len(results)))
        if web_data:
            for i, item in enumerate(web_data.get("organic", [])):
                results.append(
                    SearchResult(
                        id=f"serper-tool-{i}",
                        title=item.get("title", ""),
                        url=item.get("link", ""),
                        snippet=item.get("snippet", ""),
                        source="web",
                    )
                )

    return success_result(
        "Tool search complete",
        query=query,
        results=[r.model_dump() for r in results[:num_results]],
        count=min(len(results), num_results),
    )


# ========================
# YouTube
# ========================


def _find_existing_video(search_dir: Path, video_id: str) -> Path | None:
    """Recursively search for an existing video file with the given ID."""
    if not video_id or not search_dir.exists():
        return None

    for item in search_dir.iterdir():
        if item.is_file() and video_id in item.name:
            return item
        elif item.is_dir():
            found = _find_existing_video(item, video_id)
            if found:
                return found
    return None


def _download_youtube_video(
    url: str,
) -> dict:
    """Download a YouTube video and save it to the workspace.

    Features:
    - Downloads best quality video using yt-dlp
    - Checks for existing downloads to avoid duplicates
    - Returns file path and metadata

    Args:
        url: YouTube video URL (youtube.com or youtu.be)

    Returns:
        Dictionary with success status, file path, and metadata
    """
    start_time = time.time()

    try:
        # Validate URL
        if not url.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")

        if not ("youtube.com" in url or "youtu.be" in url):
            raise ValueError("URL must be a valid YouTube URL")

        # Extract video ID
        video_id = ""
        if "?v=" in url:
            video_id = url.split("?v=")[-1].split("&")[0]
        elif "youtu.be/" in url:
            video_id = url.split("youtu.be/")[-1].split("?")[0]

        # Check for existing file
        existing_file = _find_existing_video(Path(str(WORKSPACE)), video_id)
        if existing_file:
            return {
                "success": True,
                "message": f"Video already exists: {existing_file.name}",
                "file_path": str(existing_file),
                "file_name": existing_file.name,
                "file_size": existing_file.stat().st_size,
                "execution_time": time.time() - start_time,
                "video_id": video_id,
            }

        # Create output directory
        output_path = WORKSPACE / "youtube_downloads"
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate unique filename
        custom_filename = str(uuid.uuid4())

        # Configure yt-dlp
        ydl_opts = {
            "outtmpl": str(output_path / f"{custom_filename}.%(ext)s"),
            "format": "best",
        }

        # Download video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "Unknown")
            ydl.download([url])

        # Find downloaded file
        downloaded_files = list(output_path.glob(f"{custom_filename}.*"))
        if not downloaded_files:
            raise FileNotFoundError("Download completed but file not found")

        download_file = downloaded_files[0]

        return {
            "success": True,
            "message": f"Successfully downloaded: {title}",
            "file_path": str(download_file),
            "file_name": title,
            "file_size": download_file.stat().st_size,
            "execution_time": time.time() - start_time,
            "video_id": video_id,
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Download failed: {str(e)}",
            "execution_time": time.time() - start_time,
            "error": str(e),
            "hint": "Ensure the URL is a valid YouTube link (youtube.com or youtu.be).",
        }


# ========================
# Wikipedia
# ========================


def _search_wikipedia(
    query: str,
    limit: int = 10,
    language: str = "en",
) -> dict:
    start_time = time.time()

    try:
        if not query:
            return {
                "success": False,
                "message": "Search query cannot be empty",
                "results": [],
                "hint": "Provide a non-empty search query string.",
            }

        limit = min(limit, 20)

        wikipedia.set_lang(language)
        search_results = wikipedia.search(query, results=limit)

        results = []
        for title in search_results:
            try:
                summary = wikipedia.summary(title, sentences=1, auto_suggest=False)
                url = f"https://{language}.wikipedia.org/wiki/{title.replace(' ', '_')}"
                results.append({"title": title, "snippet": summary, "url": url})
            except Exception:
                url = f"https://{language}.wikipedia.org/wiki/{title.replace(' ', '_')}"
                results.append({"title": title, "url": url})

        return {
            "success": True,
            "message": f"Found {len(results)} results for '{query}'",
            "results": results,
            "count": len(results),
            "execution_time": time.time() - start_time,
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Search failed: {str(e)}",
            "results": [],
            "error": str(e),
            "hint": "Check your query and try again.",
        }


def _get_wikipedia_article(
    title: str,
    language: str = "en",
) -> dict:
    """Retrieve a Wikipedia article with full content, sections, categories, and links."""
    start_time = time.time()

    try:
        if not title:
            return {
                "success": False,
                "message": "Article title cannot be empty",
                "hint": "Provide a non-empty article title.",
            }

        wikipedia.set_lang(language)
        page = wikipedia.page(title, auto_suggest=True, redirect=True)

        return {
            "success": True,
            "message": f"Retrieved article: {page.title}",
            "title": page.title,
            "url": page.url,
            "summary": page.summary,
            "content": page.content,
            "sections": page.sections,
            "categories": page.categories,
            "links": page.links[:50],
            "execution_time": time.time() - start_time,
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to retrieve article: {str(e)}",
            "error": str(e),
            "hint": "Check the article title spelling or try a different title.",
        }


def _get_wikipedia_summary(
    title: str,
    sentences: int = 5,
    language: str = "en",
) -> dict:
    start_time = time.time()

    try:
        if not title:
            return {
                "success": False,
                "message": "Article title cannot be empty",
                "hint": "Provide a non-empty article title.",
            }

        wikipedia.set_lang(language)
        summary = wikipedia.summary(title, sentences=sentences, auto_suggest=True, redirect=True)
        url = f"https://{language}.wikipedia.org/wiki/{title.replace(' ', '_')}"

        return {
            "success": True,
            "message": f"Summary retrieved for: {title}",
            "title": title,
            "summary": summary,
            "url": url,
            "execution_time": time.time() - start_time,
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to retrieve summary: {str(e)}",
            "error": str(e),
            "hint": "Check the article title spelling or try a different title.",
        }


def _get_wikipedia_article_history(
    title: str,
    date: str = None,
    language: str = "en",
) -> dict:
    start_time = time.time()

    try:
        if not title:
            return {
                "success": False,
                "message": "Article title cannot be empty",
                "hint": "Provide a non-empty article title.",
            }

        wikipedia.set_lang(language)
        search_results = wikipedia.search(title, results=1)

        if search_results:
            page = wikipedia.page(search_results[0], auto_suggest=True, redirect=True)
            actual_title = page.title
        else:
            actual_title = title

        date_parts = date.split("/")
        year = int(date_parts[0])
        month = int(date_parts[1])
        day = int(date_parts[2]) if len(date_parts) > 2 else calendar.monthrange(year, month)[1]

        target_date = datetime(year, month, day)

        params = {
            "action": "query",
            "prop": "revisions",
            "titles": actual_title,
            "rvprop": "ids|timestamp|user|comment|content",
            "rvlimit": 1,
            "rvdir": "older",
            "rvstart": target_date.isoformat(),
            "format": "json",
        }

        api_url = f"https://{language}.wikipedia.org/w/api.php"
        response = requests.get(api_url, params=params, timeout=10)
        data = response.json()

        page = next(iter(data["query"]["pages"].values()))

        if "revisions" in page:
            revision = page["revisions"][0]
            actual_date = datetime.fromisoformat(revision["timestamp"].replace("Z", "+00:00"))

            rev_id = revision["revid"]
            url = f"https://{language}.wikipedia.org/w/index.php?oldid={rev_id}"

            return {
                "success": True,
                "title": actual_title,
                "url": url,
                "content": revision["*"],
                "requested_date": target_date.strftime("%Y/%m/%d"),
                "actual_date": actual_date.strftime("%Y/%m/%d"),
                "is_exact": actual_date.date() == target_date.date(),
                "editor": revision["user"],
                "comment": revision.get("comment", ""),
                "execution_time": time.time() - start_time,
            }

        return {
            "success": False,
            "message": f"No revision found for {actual_title} before {date}",
            "hint": "Try a more recent date or check the article title.",
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to retrieve historical article: {str(e)}",
            "error": str(e),
            "hint": "Check the article title and date format (YYYY/MM/DD).",
        }


# ========================
# Main tool
# ========================

_SEARCH_ALIASES: dict[str, str] = {
    # info aliases
    "web": "info",
    "google": "info",
    "internet": "info",
    "browse": "info",
    "lookup": "info",
    "search": "info",
    "query": "info",
    # image aliases
    "images": "image",
    "img": "image",
    "photo": "image",
    "picture": "image",
    "pics": "image",
    # news aliases
    "breaking": "news",
    "headlines": "news",
    "current_events": "news",
    # research aliases
    "academic": "research",
    "scholar": "research",
    "science": "research",
    "paper": "research",
    "papers": "research",
    # api aliases
    "connector": "api",
    "integration": "api",
    "mcp": "api",
    # tool aliases
    "skill": "tool",
    "plugin": "tool",
    "app": "tool",
    # data aliases
    "dataset": "data",
    "stats": "data",
    "statistics": "data",
    # youtube aliases
    "youtube": "youtube_video",
    "video": "youtube_video",
    "yt": "youtube_video",
    # wikipedia aliases
    "wiki": "wikipedia_search",
    "wikipedia": "wikipedia_search",
    "wiki_search": "wikipedia_search",
    "wiki_article": "wikipedia_article",
    "wiki_summary": "wikipedia_summary",
    "wiki_history": "wikipedia_history",
}


@tool(name="search")
async def search_tool(
    type: Annotated[
        Literal[
            "info",
            "image",
            "news",
            "research",
            "api",
            "tool",
            "data",
            "youtube_video",
            "wikipedia_search",
            "wikipedia_article",
            "wikipedia_summary",
            "wikipedia_history",
        ],
        "The category of search to perform. Determines the source and format of expected results.",
    ],
    queries: Annotated[list, "Up to 3 query variants that express the same search intent."],
    time: Annotated[
        str | None,
        "Optional time filter to limit results to a recent time range. Supported values: all, past_day, past_week, past_month, past_year.",
    ] = None,
    num_results: Annotated[int, "Maximum number of results to return."] = 5,
    safe_search: Annotated[bool, "Enable safe search filtering."] = True,
    language: Annotated[str, "Language code for results."] = "en",
    country: Annotated[str, "Country code for results."] = "us",
    sentences: Annotated[int, "Number of sentences for wikipedia_summary."] = 5,
    date: Annotated[str | None, "Date in YYYY/MM/DD format for wikipedia_history."] = None,
) -> dict:
    """Search for information across various sources.

    <instructions>
    - MUST use this tool to access up-to-date or external information when needed; DO NOT rely solely on internal knowledge.
    - MUST use this tool to collect assets before creating documents, presentations, or websites.
    - DO NOT use browser-based search result page parsing unless strictly necessary; prefer this tool instead.
    - DO NOT rely solely on search result snippets as they are often incomplete; MUST follow up by navigating to the source URLs using browser tools.
    - Each search may contain up to 3 `queries`, which MUST be variants of the same intent (i.e., query expansions), NOT different goals.
    - For non-English queries, MUST include at least one English query as the final variant to expand coverage.
    - For complex searches, MUST break down into step-by-step searches instead of using a single complex query.
    - Access multiple URLs from search results for comprehensive information or cross-validation.
    - For image results, use the attached thumbnail catalog to evaluate and select images based on the `Position` field in the result list.
    - This tool automatically downloads all result images in full resolution and provides local file paths; no manual download needed.
    - When using the downloaded images, MUST copy them into the target working directory, as the default save path may be cleared.
    - For API results, follow the returned documentation and examples to call APIs via Python.
    - MUST prioritize using APIs for bulk data access scenarios such as retrieving stock prices.
    - DO NOT use advanced search syntax (quotes, filters, operators) in queries as they are not supported.
    - Only use `time` parameter when explicitly required by task, otherwise leave time range unrestricted.
    </instructions>

    <recommended_usage>
    - Use `info` to validate facts, discover relevant articles, or cross-check content.
    - Use `image` for visual references, illustration sources, or user-requested image retrieval.
    - Use `api` to find callable APIs, MCP servers, and integrations available in the sandbox or marketplace.
    - Use `news` to retrieve breaking updates, current events, or recent announcements.
    - Use `tool` to find installed skills, apps, or plugins that can perform specific operations.
    - Use `data` to locate reliable datasets or statistical information from sources like SimilarWeb or Yahoo Finance.
    - Use `research` to support academic, technical, or policy-related tasks with credible publications.
    - Use `youtube_video` to download YouTube videos for analysis or reference.
    - Use `wikipedia_search` to find Wikipedia articles matching a query.
    - Use `wikipedia_article` to retrieve full Wikipedia article content.
    - Use `wikipedia_summary` for quick summaries of Wikipedia topics.
    - Use `wikipedia_history` to access historical versions of Wikipedia articles.
    </recommended_usage>
    """
    type, _alias = resolve_alias(type, _SEARCH_ALIASES)

    try:
        if not queries:
            return error_result(
                "Missing required parameter: queries. Provide at least one query string.",
                hint="Use queries=['your search term'] with at least one element.",
            )
        query = queries[0]
        if not query or not str(query).strip():
            return error_result("First query element is empty.", hint="Provide a non-empty search term in queries[0].")

        if type == "info":
            return alias_hint(
                await asyncio.to_thread(
                    _search_serper,
                    query=query,
                    num_results=num_results,
                ),
                _alias,
                type,
                param_name="type",
            )
        elif type == "image":
            return alias_hint(
                await asyncio.to_thread(
                    _search_serper_images,
                    query=query,
                    num_results=num_results,
                ),
                _alias,
                type,
                param_name="type",
            )
        elif type == "news":
            return alias_hint(
                await asyncio.to_thread(
                    _search_serper_news,
                    query=query,
                    num_results=num_results,
                ),
                _alias,
                type,
                param_name="type",
            )
        elif type == "research":
            return alias_hint(
                await asyncio.to_thread(
                    _search_serper_scholar,
                    query=query,
                    num_results=num_results,
                ),
                _alias,
                type,
                param_name="type",
            )
        elif type == "api":
            return alias_hint(
                await asyncio.to_thread(
                    _search_api,
                    query=query,
                    num_results=num_results,
                ),
                _alias,
                type,
                param_name="type",
            )
        elif type == "tool":
            return alias_hint(
                await asyncio.to_thread(
                    _search_tool,
                    query=query,
                    num_results=num_results,
                ),
                _alias,
                type,
                param_name="type",
            )
        elif type == "data":
            return alias_hint(
                await asyncio.to_thread(
                    _search_serper,
                    query=query,
                    num_results=num_results,
                ),
                _alias,
                type,
                param_name="type",
            )
        elif type == "youtube_video":
            return alias_hint(
                await asyncio.to_thread(_download_youtube_video, url=query), _alias, type, param_name="type"
            )
        elif type == "wikipedia_search":
            return alias_hint(
                await asyncio.to_thread(
                    _search_wikipedia,
                    query=query,
                    limit=num_results,
                    language=language,
                ),
                _alias,
                type,
                param_name="type",
            )
        elif type == "wikipedia_article":
            return alias_hint(
                await asyncio.to_thread(
                    _get_wikipedia_article,
                    title=query,
                    language=language,
                ),
                _alias,
                type,
                param_name="type",
            )
        elif type == "wikipedia_summary":
            return alias_hint(
                await asyncio.to_thread(
                    _get_wikipedia_summary,
                    title=query,
                    sentences=sentences,
                    language=language,
                ),
                _alias,
                type,
                param_name="type",
            )
        elif type == "wikipedia_history":
            return alias_hint(
                await asyncio.to_thread(
                    _get_wikipedia_article_history,
                    title=query,
                    date=date,
                    language=language,
                ),
                _alias,
                type,
                param_name="type",
            )
        else:
            return error_result(
                f"Unknown search type: '{type}'.",
                hint="Valid types: info, image, news, research, api, tool, data, youtube_video, wikipedia_search, wikipedia_article, wikipedia_summary, wikipedia_history.",
            )
    except Exception as e:
        logger.exception("search_tool error: %s", e)
        return error_result(
            f"Search operation failed: {e}", hint="An unexpected error occurred. Check search API keys and try again."
        )


SEARCH_TOOLS = [search_tool]
