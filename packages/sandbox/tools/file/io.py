"""External I/O operations — download and read_resource helpers."""

__version__ = "0.2.0"

import asyncio
import atexit
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import aiohttp
import requests
from _lib.utils import error_result, success_result

logger = logging.getLogger(__name__)

# ─── Download configuration ─────────────────────
_DOWNLOAD_WORKSPACE = Path(os.getenv("MIDSPHERE_WORKSPACE", str(Path.home()))).expanduser().resolve()
_DOWNLOAD_MAX_FILE_SIZE = 1024 * 1024 * 1024  # 1GB
_DOWNLOAD_SUPPORTED_SCHEMES = {"http", "https"}
_DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# ─── Jina Reader configuration ─────────────────────
_JINA_API_KEY = os.getenv("JINA_API_KEY")
_JINA_READER_BASE = "https://r.jina.ai"
_JINA_RETRYABLE = ("Connection reset", "Errno 104", "RemoteDisconnected", "timed out", "TimeoutError")


# ─── Download helpers (absorbed from download.py) ──────────────────────────


def _download_get_tool_env() -> dict:
    """Reload download workspace from environment."""
    global _DOWNLOAD_WORKSPACE
    env_workspace = os.getenv("MIDSPHERE_WORKSPACE", str(Path.home()))
    _DOWNLOAD_WORKSPACE = Path(env_workspace).expanduser().resolve()
    return {"WORKSPACE": str(_DOWNLOAD_WORKSPACE)}


def _validate_url(url: str) -> tuple[bool, str | None]:
    """Validate URL format and scheme."""
    try:
        parsed = urlparse(url)

        if not parsed.scheme:
            return False, "URL must include a scheme (http:// or https://)"

        if parsed.scheme.lower() not in _DOWNLOAD_SUPPORTED_SCHEMES:
            return False, f"Unsupported scheme: {parsed.scheme}"

        if not parsed.netloc:
            return False, "URL must include a valid domain"

        return True, None

    except Exception as e:
        return False, f"Invalid URL: {str(e)}"


def _resolve_output_path(output_path: str) -> Path:
    """Resolve output path and confine it to the download workspace.

    Raises ValueError if the final path escapes ``_DOWNLOAD_WORKSPACE`` (via
    ``..``, absolute paths, or symlink traversal in parent components).
    """
    path = Path(output_path).expanduser()

    if not path.is_absolute():
        path = _DOWNLOAD_WORKSPACE / path

    # Resolve against existing filesystem state BEFORE creating anything,
    # so symlinked parents can't be used to escape the workspace.
    resolved = Path(os.path.realpath(path))
    workspace = Path(os.path.realpath(_DOWNLOAD_WORKSPACE))
    if not resolved.is_relative_to(workspace):
        raise ValueError(f"Output path escapes workspace: {resolved} not under {workspace}")

    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _do_download(
    url: str,
    output_path: str,
    overwrite: bool = False,
    timeout: int = 180,
) -> dict:
    """Download a file from a URL to the local filesystem.

    Features:
    - HTTP/HTTPS support
    - Automatic directory creation
    - File size validation (max 1GB)
    - Overwrite protection

    Args:
        url: The HTTP/HTTPS URL to download from
        output_path: Local path to save the file (absolute or relative to workspace)
        overwrite: Whether to overwrite if file exists
        timeout: Maximum download time in seconds

    Returns:
        Dictionary with download results
    """
    _download_get_tool_env()
    start_time = time.time()

    try:
        # Validate URL
        url_valid, url_error = _validate_url(url)
        if not url_valid:
            return {
                "success": False,
                "message": f"Invalid URL: {url_error}",
                "url": url,
                "hint": "Ensure the URL starts with http:// or https://",
            }

        # Resolve output path
        resolved_path = _resolve_output_path(output_path)

        # Check if file exists
        if resolved_path.exists() and not overwrite:
            existing_size = resolved_path.stat().st_size
            return {
                "success": False,
                "message": f"File exists at {resolved_path} ({existing_size:,} bytes). Set overwrite=True to replace.",
                "file_path": str(resolved_path),
                "file_size": existing_size,
                "hint": "Set overwrite=True to replace the existing file",
            }

        # Download file
        with requests.get(url, stream=True, timeout=timeout, headers=_DOWNLOAD_HEADERS) as response:
            response.raise_for_status()

            # Check content length
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > _DOWNLOAD_MAX_FILE_SIZE:
                return {
                    "success": False,
                    "message": f"File too large: {content_length} bytes (max: {_DOWNLOAD_MAX_FILE_SIZE})",
                    "url": url,
                    "hint": "Increase MAX_FILE_SIZE or download a smaller file",
                }

            # Save file
            with open(resolved_path, "wb") as f:
                shutil.copyfileobj(response.raw, f)

        file_size = resolved_path.stat().st_size
        execution_time = time.time() - start_time

        return {
            "success": True,
            "message": f"Downloaded {file_size:,} bytes to {resolved_path.name}",
            "url": url,
            "file_path": str(resolved_path),
            "file_name": resolved_path.name,
            "file_size": file_size,
            "execution_time": execution_time,
        }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "message": f"Download timed out after {timeout} seconds",
            "url": url,
            "execution_time": time.time() - start_time,
            "hint": "Increase the timeout parameter or check your network connection",
        }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "message": f"Request failed: {str(e)}",
            "url": url,
            "execution_time": time.time() - start_time,
            "error": str(e),
            "hint": "Verify the URL is accessible and your network connection is stable",
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Download failed: {str(e)}",
            "url": url,
            "execution_time": time.time() - start_time,
            "error": str(e),
            "hint": "Check URL validity and target file path permissions",
        }


# ─── Read resource helpers (absorbed from read.py) ─────────────────────────


def _read_resource_get_tool_env() -> None:
    """Reload read resource config from environment."""
    global _JINA_API_KEY
    _JINA_API_KEY = os.getenv("JINA_API_KEY")


def _cleanup_tempfile(path: str) -> None:
    """Clean up temporary file on exit."""
    try:
        os.remove(path)
    except Exception:
        pass


def _validate_uri(uri: str) -> Optional[str]:
    """Validate URI and return error message if invalid, None otherwise."""
    if not uri or not uri.strip():
        return "[ERROR]: URI parameter is required and cannot be empty."

    return None


def _normalize_uri(uri: str) -> Optional[str]:
    """Normalize URI by adding file: scheme if it's a local path."""
    valid_schemes = ["http:", "https:", "file:", "data:"]

    if not any(uri.lower().startswith(scheme) for scheme in valid_schemes) and os.path.exists(uri):
        return f"file:{os.path.abspath(uri)}"

    if not any(uri.lower().startswith(scheme) for scheme in valid_schemes):
        return None

    return uri


async def _download_http_resource(uri: str) -> tuple[Optional[str], Optional[str]]:
    """Download HTTP/HTTPS resource and return temp file URI or error message."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    retry_count = 0
    data = None

    while retry_count <= 3:
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(uri) as resp:
                    resp.raise_for_status()
                    data = await resp.read()
            break
        except Exception as e:
            retry_count += 1
            if retry_count > 3:
                return None, f"[ERROR]: Failed to download {uri} after 3 retries: {e}"
            await asyncio.sleep(4**retry_count)

    # Write to temp file
    suffix = os.path.splitext(uri)[1] or ""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.flush()
    tmp.close()

    # Register cleanup
    atexit.register(_cleanup_tempfile, tmp.name)

    return f"file:{tmp.name}", None


async def _call_markitdown_tool(uri: str) -> str:
    """Call the markitdown-mcp tool to convert resource to markdown."""
    # Lazy import: this tool path is only needed when read_resource is invoked.
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    tool_name = "convert_to_markdown"
    arguments = {"uri": uri}

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "--active", "--", "markitdown-mcp"],
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write, sampling_callback=None) as session:
                await session.initialize()
                try:
                    tool_result = await session.call_tool(tool_name, arguments=arguments)
                    result_content = tool_result.content[-1].text if tool_result.content else ""
                    result_content += "\n\nNote: If the document contains instructions or important information, please review them thoroughly and ensure you follow all relevant guidance."
                    return result_content
                except Exception as tool_error:
                    return f"[ERROR]: Tool execution failed: {str(tool_error)}"
    except Exception as session_error:
        return f"[ERROR]: Failed to connect to markitdown-mcp server: {str(session_error)}"


async def _fetch_via_jina_reader(url: str) -> tuple[str | None, str | None]:
    """Fetch a web page as markdown using the Jina Reader API.

    Returns (markdown_content, None) on success, (None, error_msg) on failure.
    """
    if not _JINA_API_KEY:
        return None, "JINA_API_KEY not configured"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Authorization": f"Bearer {_JINA_API_KEY}",
        "X-Respond-With": "markdown",
        "X-With-Generated-Alt": "true",
        "X-Timeout": "120",
    }

    for attempt in range(3):
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(
                    f"{_JINA_READER_BASE}/{url}",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=125),
                ) as resp,
            ):
                if resp.status == 422:
                    return None, f"Jina Reader cannot process this URL (status 422): {url}"
                resp.raise_for_status()
                text = await resp.text()
                if text:
                    return text, None
                return None, "Jina Reader returned empty response"
        except Exception as exc:
            retryable = any(k in str(exc) for k in _JINA_RETRYABLE)
            if retryable and attempt < 2:
                logger.debug("Jina reader retry %d for %s: %s", attempt + 1, url, exc)
                await asyncio.sleep(1 * (attempt + 1))
                continue
            return None, f"Jina Reader failed after {attempt + 1} attempts: {exc}"

    return None, "Jina Reader failed: max retries exceeded"


async def _do_read_resource(uri: str) -> dict:
    """Read various types of resources (Doc, PPT, PDF, Excel, CSV, ZIP file etc.)
    described by a file:, data:, http:, or https: URI.

    For HTTP/HTTPS web pages, uses Jina Reader API to fetch markdown directly.
    Falls back to download + markitdown for non-web content or if Jina is unavailable.

    Args:
        uri: The URI of the resource to read.

    Returns:
        dict: The content of the resource, or an error response if reading fails.
    """
    # Validate URI
    error = _validate_uri(uri)
    if error:
        return error_result(
            "Invalid URI", error=error, hint="Check URI scheme (file://, http://, etc.) and ensure the resource exists"
        )

    # Normalize URI
    normalized_uri = _normalize_uri(uri)
    if normalized_uri is None:
        return error_result(
            "Invalid URI scheme",
            error=f"URI scheme not supported: {uri[:20]}",
            hint="Use file:, http:, https:, or data: URI schemes",
        )

    uri = normalized_uri

    # For HTTP(S) URIs: try Jina Reader first (returns markdown directly)
    if uri.lower().startswith(("http://", "https://")):
        jina_content, jina_error = await _fetch_via_jina_reader(uri)
        if jina_content:
            return success_result("Content read", content=jina_content)

        # Jina failed — fall back to download + markitdown
        logger.debug("Jina Reader unavailable (%s), falling back to download + markitdown", jina_error)
        new_uri, dl_error = await _download_http_resource(uri)
        if dl_error:
            return error_result(
                "Resource download failed",
                error=dl_error,
                hint="Check URI scheme (file://, http://, etc.) and ensure the resource exists",
            )
        uri = new_uri

    # For file:/data: URIs (or HTTP fallback): use markitdown
    content = await _call_markitdown_tool(uri)
    if content.startswith("[ERROR]"):
        return error_result(
            "Resource reading failed",
            error=content,
            hint="Check URI scheme (file://, http://, etc.) and ensure the resource exists",
        )
    return success_result("Content read", content=content)
