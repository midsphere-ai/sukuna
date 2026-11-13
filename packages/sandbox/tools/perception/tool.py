"""
Unified Perception Tool

This module merges vision (image/video) and audio tools into a single
`perception_tool` with auto-detection of media type from file extension or URL.

Supported media:
- Images: .png, .jpg, .jpeg, .gif, .webp, .bmp, .svg
- Videos: .mp4, .avi, .mov, .mkv, .webm, or YouTube URLs
- Audio: .mp3, .wav, .ogg, .flac, .m4a, .aac

Actions: analyze, transcribe, compare, extract
"""

__version__ = "0.1.0"

import asyncio
import base64
import contextlib
import logging
import mimetypes
import os
import wave
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import unquote, urlparse

from _lib.utils import alias_hint, error_result, resolve_alias
from exo import tool

logger = logging.getLogger(__name__)


# ========================
# Media type constants
# ========================

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"}


def _detect_media_type(source: str) -> str:
    """Detect media type from file extension or URL pattern."""
    if "youtube.com" in source or "youtu.be" in source:
        return "youtube"
    ext = os.path.splitext(source)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    return "unknown"


# ========================
# Vision API Keys and configurations
# ========================

VISION_LLM_API_KEY = os.environ.get("MANAGED_VISION_LLM_API_KEY") or os.environ.get("LLM_API_KEY")
VISION_LLM_BASE_URL = os.environ.get("MANAGED_VISION_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL", "")
VISION_LLM_MODEL_NAME = os.environ.get("MANAGED_VISION_LLM_MODEL") or os.environ.get("LLM_MODEL_NAME")
VISION_LLM_MODEL_PROVIDER = os.environ.get("MANAGED_VISION_LLM_PROVIDER") or os.environ.get("LLM_MODEL_PROVIDER")
VISION_LLM_MODEL_TEMPERATURE = os.environ.get("LLM_MODEL_TEMPERATURE")

# Workspace configuration
WORKSPACE = Path(os.getenv("MIDSPHERE_WORKSPACE", "~")).expanduser()

# ========================
# Audio API Keys and configurations
# ========================

AUDIO_LLM_API_KEY = os.environ.get("MANAGED_AUDIO_LLM_API_KEY") or os.environ.get("LLM_API_KEY")
AUDIO_LLM_BASE_URL = os.environ.get("MANAGED_AUDIO_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL", "")
AUDIO_LLM_MODEL_NAME = os.environ.get("MANAGED_AUDIO_LLM_MODEL") or os.environ.get("LLM_MODEL_NAME")
AUDIO_LLM_MODEL_PROVIDER = os.environ.get("MANAGED_AUDIO_LLM_PROVIDER") or os.environ.get("LLM_MODEL_PROVIDER")
AUDIO_LLM_MODEL_TEMPERATURE = os.environ.get("LLM_MODEL_TEMPERATURE")
AUDIO_LLM_MODEL_TRANSCRIPTION_NAME = os.environ.get("LLM_MODEL_TRANSCRIPTION_NAME")


# ========================
# Lazy-loaded modules (vision)
# ========================

_cv2_module = None
_np_module = None
_Anthropic = None
_OpenAI = None
_AzureOpenAI = None

# Audio client cache
_AUDIO_CLIENT_CACHE: dict[tuple[str, str | None, str | None], object] = {}


def get_tool_env():
    """Refresh all environment variables for both vision and audio."""
    global VISION_LLM_API_KEY, VISION_LLM_BASE_URL, VISION_LLM_MODEL_NAME
    global VISION_LLM_MODEL_PROVIDER, VISION_LLM_MODEL_TEMPERATURE
    global AUDIO_LLM_API_KEY, AUDIO_LLM_BASE_URL, AUDIO_LLM_MODEL_NAME
    global AUDIO_LLM_MODEL_PROVIDER, AUDIO_LLM_MODEL_TEMPERATURE
    global AUDIO_LLM_MODEL_TRANSCRIPTION_NAME

    VISION_LLM_API_KEY = os.environ.get("MANAGED_VISION_LLM_API_KEY") or os.environ.get("LLM_API_KEY")
    VISION_LLM_BASE_URL = os.environ.get("MANAGED_VISION_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL", "")
    VISION_LLM_MODEL_NAME = os.environ.get("MANAGED_VISION_LLM_MODEL") or os.environ.get("LLM_MODEL_NAME")
    VISION_LLM_MODEL_PROVIDER = os.environ.get("MANAGED_VISION_LLM_PROVIDER") or os.environ.get("LLM_MODEL_PROVIDER")
    VISION_LLM_MODEL_TEMPERATURE = os.environ.get("LLM_MODEL_TEMPERATURE")

    AUDIO_LLM_API_KEY = os.environ.get("MANAGED_AUDIO_LLM_API_KEY") or os.environ.get("LLM_API_KEY")
    AUDIO_LLM_BASE_URL = os.environ.get("MANAGED_AUDIO_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL", "")
    AUDIO_LLM_MODEL_NAME = os.environ.get("MANAGED_AUDIO_LLM_MODEL") or os.environ.get("LLM_MODEL_NAME")
    AUDIO_LLM_MODEL_PROVIDER = os.environ.get("MANAGED_AUDIO_LLM_PROVIDER") or os.environ.get("LLM_MODEL_PROVIDER")
    AUDIO_LLM_MODEL_TEMPERATURE = os.environ.get("LLM_MODEL_TEMPERATURE")
    AUDIO_LLM_MODEL_TRANSCRIPTION_NAME = os.environ.get("LLM_MODEL_TRANSCRIPTION_NAME")


# =============================================================================
# Vision lazy loaders
# =============================================================================


def _get_cv2_np():
    global _cv2_module, _np_module
    if _cv2_module is None or _np_module is None:
        import cv2 as _cv2
        import numpy as _np

        _cv2_module = _cv2
        _np_module = _np
    return _cv2_module, _np_module


def _get_anthropic_cls():
    global _Anthropic
    if _Anthropic is None:
        from anthropic import Anthropic as _LoadedAnthropic

        _Anthropic = _LoadedAnthropic
    return _Anthropic


def _get_openai_classes():
    global _OpenAI, _AzureOpenAI
    if _OpenAI is None or _AzureOpenAI is None:
        from openai import AzureOpenAI as _LoadedAzureOpenAI
        from openai import OpenAI as _LoadedOpenAI

        _OpenAI = _LoadedOpenAI
        _AzureOpenAI = _LoadedAzureOpenAI
    return _OpenAI, _AzureOpenAI


# =============================================================================
# Audio client helpers
# =============================================================================


def _get_audio_openai_client():
    if AUDIO_LLM_MODEL_PROVIDER == "azure_openai":
        from openai import AzureOpenAI

        cache_key = ("azure_openai", AUDIO_LLM_API_KEY, AUDIO_LLM_BASE_URL)
        client = _AUDIO_CLIENT_CACHE.get(cache_key)
        if client is None:
            client = AzureOpenAI(
                api_key=AUDIO_LLM_API_KEY,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
                azure_endpoint=AUDIO_LLM_BASE_URL,
            )
            _AUDIO_CLIENT_CACHE[cache_key] = client
        return client

    from openai import OpenAI

    cache_key = ("openai", AUDIO_LLM_API_KEY, AUDIO_LLM_BASE_URL)
    client = _AUDIO_CLIENT_CACHE.get(cache_key)
    if client is None:
        client = OpenAI(api_key=AUDIO_LLM_API_KEY, base_url=AUDIO_LLM_BASE_URL or None)
        _AUDIO_CLIENT_CACHE[cache_key] = client
    return client


def _get_audio_transcription_model():
    if AUDIO_LLM_MODEL_PROVIDER == "azure_openai":
        return AUDIO_LLM_MODEL_TRANSCRIPTION_NAME
    else:
        return AUDIO_LLM_MODEL_NAME


def _get_audio_model():
    return AUDIO_LLM_MODEL_NAME


def get_audio_extension(url: str, content_type: str = None) -> str:
    """
    Determine the appropriate audio file extension from URL or content type.

    Args:
        url: The URL of the audio file
        content_type: The content type from HTTP headers

    Returns:
        File extension (with dot) to use for temporary file
    """
    # First try to get extension from URL
    parsed_url = urlparse(url)
    path = parsed_url.path.lower()

    # Common audio extensions
    audio_extensions = [".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".wma"]
    for ext in audio_extensions:
        if path.endswith(ext):
            return ext

    # If no extension found in URL, try content type
    if content_type:
        content_type = content_type.lower()
        if "mp3" in content_type or "mpeg" in content_type:
            return ".mp3"
        elif "wav" in content_type:
            return ".wav"
        elif "m4a" in content_type:
            return ".m4a"
        elif "aac" in content_type:
            return ".aac"
        elif "ogg" in content_type:
            return ".ogg"
        elif "flac" in content_type:
            return ".flac"

    # Default fallback to mp3
    return ".mp3"


def get_audio_duration(audio_path: str) -> float:
    """
    Get audio duration in seconds.

    Tries to use wave (for .wav), then falls back to mutagen (for mp3, etc).
    """
    # Try using wave for .wav files
    try:
        with contextlib.closing(wave.open(audio_path, "rb")) as f:
            frames = f.getnframes()
            rate = f.getframerate()
            duration = frames / float(rate)
            if duration > 0:
                return duration
    except Exception:
        pass  # Not a wav file or failed

    # Try using mutagen for other audio formats (mp3, etc)
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(audio_path)
        if audio is not None and hasattr(audio, "info") and hasattr(audio.info, "length"):
            duration = float(audio.info.length)
            if duration > 0:
                return duration
    except Exception as e:
        return f"[ERROR]: Failed to get audio duration: {e}"


def encode_audio_file(audio_path: str) -> tuple[str, str]:
    """Encode audio file to base64 and determine format."""
    with open(audio_path, "rb") as audio_file:
        audio_data = audio_file.read()
        encoded_string = base64.b64encode(audio_data).decode("utf-8")

    # Determine file format from file extension
    mime_type, _ = mimetypes.guess_type(audio_path)
    if mime_type and mime_type.startswith("audio/"):
        mime_format = mime_type.split("/")[-1]
        # Map MIME type formats to OpenAI supported formats
        format_mapping = {
            "mpeg": "mp3",  # audio/mpeg -> mp3
            "wav": "wav",  # audio/wav -> wav
            "wave": "wav",  # audio/wave -> wav
        }
        file_format = format_mapping.get(mime_format, "mp3")
    else:
        # Default to mp3 if we can't determine
        file_format = "mp3"

    return encoded_string, file_format


# =============================================================================
# Vision Prompts
# =============================================================================

OCR_PROMPT = """You are a meticulous text extraction specialist. Your task is to carefully scan the entire image and extract ALL visible text with maximum accuracy.

IMPORTANT INSTRUCTIONS:
1. **Scan systematically** - Look at every corner, edge, and area of the image multiple times
2. **Extract ALL text** - Include headers, labels, captions, fine print, watermarks, signs, and any other text elements
3. **Preserve formatting** - Maintain line breaks, spacing, and text hierarchy as they appear
4. **Include numbers and symbols** - Extract all numerical values, symbols, and special characters
5. **Double-check your work** - Review the entire image again to ensure nothing was missed
6. **Describe any unclear, partially visible, or ambiguous text** - If any text is blurry, cut off, partly obscured, or otherwise difficult to read, **describe it as best as possible, even if you are unsure or cannot fully recognize it**.

Remember: Your extraction will be used by someone who cannot see the image themselves. Any possible guess, uncertainty, or ambiguity should be reported in words rather than left out, so that nothing is omitted or lost.

Return only the extracted text content, maintaining the original formatting and structure as much as possible. If there is no text in the image, respond with 'No text found'. If there are areas where text may exist but is unreadable or ambiguous, describe these as well."""

VQA_PROMPT = """You are a highly attentive visual analysis assistant. Your task is to carefully examine the image and provide a thorough, accurate answer to the question.

IMPORTANT INSTRUCTIONS:
1. **Look at the image multiple times** - Take your time to observe all details, objects, people, text, colors, spatial relationships, and any subtle elements
2. **Cross-reference with OCR data** - Carefully compare what you see visually with the extracted text to ensure consistency
3. **Think step-by-step** - Break down your analysis into logical steps before providing your final answer, especially for complex and multi-object recognition questions
4. **Consider multiple perspectives** - Look at the image from different angles and consider various interpretations, especially for multi-object recognition questions
5. **Double-check your observations** - Verify your initial impressions by looking again at specific areas, especially for complex and multi-object recognition questions
6. **Be precise and detailed** - Provide specific details rather than general observations
7. **Report all visible or possible content, even if uncertain or ambiguous** - If you notice anything that is blurry, partly obscured, difficult to recognize, or of uncertain importance, **describe it in words instead of omitting it**. Do not leave out any possible content, even if you are unsure.

Remember: Your analysis will be used by someone who cannot see the image themselves. Any possible guess, uncertainty, or ambiguity should be reported in words rather than left out, so that nothing is omitted or lost.

The OCR result of this image is as follows (may be incomplete or missing some text):
{ocr_result}

Question to answer: {question}

Please provide a comprehensive analysis that demonstrates careful observation and thoughtful reasoning, including any possible, uncertain, or ambiguous elements you notice."""

VIDEO_ANALYZE_PROMPT = (
    "Input is a sequence of video frames. Given user's task: {task}. "
    "analyze the video content following these steps:\n"
    "1. Temporal sequence understanding\n"
    "2. Motion and action analysis\n"
    "3. Scene context interpretation\n"
    "4. Object and person tracking\n"
)

VIDEO_SUMMARIZE_PROMPT = (
    "Input is a sequence of video frames. "
    "Summarize the main content of the video. "
    "Include key points, main topics, and important visual elements. "
)


# =============================================================================
# Image Processing Helpers
# =============================================================================


async def detect_image_format(file_path: str) -> str:
    """Detect image format from file header."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(16)
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        elif header.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        elif header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
            return "image/gif"
        elif header.startswith(b"RIFF") and b"WEBP" in header:
            return "image/webp"
        else:
            return await guess_mime_media_type_from_extension(file_path)
    except Exception:
        return await guess_mime_media_type_from_extension(file_path)


async def guess_mime_media_type_from_extension(file_path: str) -> str:
    """Guess the MIME type based on the file extension."""
    _, ext = os.path.splitext(file_path)
    ext = ext.lower()
    if ext in [".jpg", ".jpeg"]:
        return "image/jpeg"
    elif ext == ".png":
        return "image/png"
    elif ext == ".gif":
        return "image/gif"
    elif ext == ".webp":
        return "image/webp"
    else:
        return "image/jpeg"


# =============================================================================
# Vision LLM Clients
# =============================================================================


async def call_claude_vision(image_path_or_url: str, question: str) -> str:
    """Call Claude vision API."""
    messages_for_llm = [
        {
            "role": "user",
            "content": [
                {"type": "image", "source": None},
                {"type": "text", "text": question},
            ],
        }
    ]

    try:
        parsed = urlparse(image_path_or_url)
        if parsed.scheme == "file":
            image_path_or_url = unquote(parsed.path)

        if os.path.exists(image_path_or_url):
            with open(image_path_or_url, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode("utf-8")
                messages_for_llm[0]["content"][0]["source"] = dict(
                    type="base64",
                    media_type=await detect_image_format(image_path_or_url),
                    data=image_data,
                )
        else:
            url = image_path_or_url
            if url.startswith("http://"):
                url = url.replace("http://", "https://", 1)
            elif not url.startswith("https://"):
                url = "https://" + url
            messages_for_llm[0]["content"][0]["source"] = dict(type="url", url=url)

        max_retries = 4
        for attempt in range(1, max_retries + 1):
            try:
                client = _get_anthropic_cls()(
                    api_key=VISION_LLM_API_KEY,
                    base_url=VISION_LLM_BASE_URL,
                )
                response = client.messages.create(
                    model=VISION_LLM_MODEL_NAME,
                    max_tokens=4096,
                    messages=messages_for_llm,
                )
                result = response.content[0].text
                if result is None or result.strip() == "":
                    raise Exception("Response text is None or empty")
                break
            except Exception as e:
                if attempt == max_retries:
                    result = (
                        f"[ERROR]: Visual Question Answering (Claude Client) failed after {max_retries} retries: {e}\n"
                    )
                    break
                await asyncio.sleep(4**attempt)

        return result

    except Exception as e:
        return f"[ERROR]: Claude Error: {e}"


async def call_openai_vision(image_path_or_url: str, question: str) -> str:
    """Call OpenAI vision API (supports Azure OpenAI)."""
    try:
        if os.path.exists(image_path_or_url):
            with open(image_path_or_url, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode("utf-8")
                mime_type = await detect_image_format(image_path_or_url)
                image_content = {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                }
        else:
            image_content = {
                "type": "image_url",
                "image_url": {"url": image_path_or_url},
            }

        messages_for_llm = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    image_content,
                ],
            }
        ]

        if VISION_LLM_MODEL_PROVIDER == "azure_openai":
            client = _get_openai_classes()[1](
                api_key=VISION_LLM_API_KEY,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", ""),
                azure_endpoint=VISION_LLM_BASE_URL,
            )
            model = VISION_LLM_MODEL_NAME
        else:
            client = _get_openai_classes()[0](
                api_key=VISION_LLM_API_KEY,
                base_url=VISION_LLM_BASE_URL,
            )
            model = VISION_LLM_MODEL_NAME

        response = client.chat.completions.create(
            model=model,
            messages=messages_for_llm,
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"[ERROR]: OpenAI/Azure Error: {e}"


# =============================================================================
# Video Processing Helpers
# =============================================================================


def get_video_frames(
    video_source: str,
    sample_rate: int = 2,
    start_time: float = 0,
    end_time: float | None = None,
) -> list[dict[str, any]]:
    """Extract frames from video with given sample rate."""
    try:
        if not os.path.exists(video_source):
            raise ValueError(f"Video file not found: {video_source}")

        video = _get_cv2_np()[0].VideoCapture(video_source)
        if not video.isOpened():
            raise ValueError(f"Could not open video file: {video_source}")

        fps = video.get(_get_cv2_np()[0].CAP_PROP_FPS)
        frame_count = int(video.get(_get_cv2_np()[0].CAP_PROP_FRAME_COUNT))
        video_duration = frame_count / fps

        if end_time is None:
            end_time = video_duration

        if start_time > end_time:
            raise ValueError("Start time cannot be greater than end time.")

        start_time = max(0, start_time)
        end_time = min(end_time, video_duration)

        start_frame = int(start_time * fps)
        end_frame = int(end_time * fps)

        all_frames = []
        frames = []

        frame_interval = max(1, int(fps / sample_rate))

        video.set(_get_cv2_np()[0].CAP_PROP_POS_FRAMES, start_frame)

        for i in range(start_frame, end_frame):
            ret, frame = video.read()
            if not ret:
                break

            _, buffer = _get_cv2_np()[0].imencode(".jpg", frame)
            frame_data = base64.b64encode(buffer).decode("utf-8")
            frame_data = f"data:image/jpeg;base64,{frame_data}"

            all_frames.append({"data": frame_data, "time": i / fps})

        for i in range(0, len(all_frames), frame_interval):
            frames.append(all_frames[i])

        video.release()

        if not frames:
            raise ValueError(f"Could not extract any frames from video: {video_source}")

        return frames

    except Exception as e:
        raise ValueError(f"Error extracting frames from {video_source}: {str(e)}")


def create_video_content_for_llm(
    prompt: str, video_frames: list[dict[str, any]], provider: str = "openai"
) -> list[dict[str, any]]:
    """Create uniform video format for querying LLM."""
    content = [{"type": "text", "text": prompt}]

    if "anthropic" in provider.lower():
        for frame in video_frames:
            parts = frame["data"].split(",")
            image_format = parts[0].split(":")[1].split(";")[0]
            frame_data_only = parts[1]
            content.append(
                {"type": "image", "source": {"type": "base64", "media_type": image_format, "data": frame_data_only}}
            )
    else:
        # OpenAI and Azure OpenAI support the same image_url format
        content.extend([{"type": "image_url", "image_url": {"url": frame["data"]}} for frame in video_frames])

    return content


def extract_keyframes_with_scene_detection(
    video_path: str, target_time: int, window_size: int
) -> tuple[list[any], list[float]]:
    """Extract key frames around the target time with scene detection."""
    cap = _get_cv2_np()[0].VideoCapture(video_path)
    fps = cap.get(_get_cv2_np()[0].CAP_PROP_FPS)

    start_frame = int((target_time - window_size / 2) * fps)
    end_frame = int((target_time + window_size / 2) * fps)
    total_frames_in_window = end_frame - start_frame

    max_frames = 384

    if total_frames_in_window <= max_frames:
        frame_interval = 1
        use_scene_detection = True
    else:
        frame_interval = total_frames_in_window // max_frames
        use_scene_detection = False

    frames = []
    frame_times = []

    cap.set(_get_cv2_np()[0].CAP_PROP_POS_FRAMES, max(0, start_frame))

    prev_frame = None
    frame_count = 0

    while cap.isOpened() and len(frames) < max_frames:
        frame_pos = cap.get(_get_cv2_np()[0].CAP_PROP_POS_FRAMES)
        if frame_pos >= end_frame:
            break

        ret, frame = cap.read()
        if not ret:
            break

        if use_scene_detection:
            gray = _get_cv2_np()[0].cvtColor(frame, _get_cv2_np()[0].COLOR_BGR2GRAY)

            if prev_frame is None:
                frames.append(frame)
                frame_times.append(frame_pos / fps)
            else:
                diff = _get_cv2_np()[0].absdiff(gray, prev_frame)
                mean_diff = _get_cv2_np()[1].mean(diff)

                if mean_diff > 20:
                    frames.append(frame)
                    frame_times.append(frame_pos / fps)

            prev_frame = gray
        else:
            if frame_count % frame_interval == 0:
                frames.append(frame)
                frame_times.append(frame_pos / fps)

            frame_count += 1

    cap.release()
    return frames, frame_times


def save_keyframes(frames: list[any], frame_times: list[float], output_dir: str) -> tuple[list[str], list[float]]:
    """Save extracted frames to disk."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    saved_timestamps = []

    for frame, timestamp in zip(frames, frame_times):
        filename = output_path / f"frame_{timestamp:.2f}s.jpg"
        _get_cv2_np()[0].imwrite(str(filename), frame)
        saved_paths.append(str(filename))
        saved_timestamps.append(timestamp)

    return saved_paths, saved_timestamps


# =============================================================================
# Unified perception tool
# =============================================================================

_PERCEPTION_ALIASES: dict[str, str] = {
    "describe": "analyze",
    "inspect": "analyze",
    "examine": "analyze",
    "study": "analyze",
    "review": "analyze",
    "understand": "analyze",
    "explain": "analyze",
    "speech_to_text": "transcribe",
    "stt": "transcribe",
    "convert": "transcribe",
    "listen": "transcribe",
    "caption": "transcribe",
    "diff": "compare",
    "contrast": "compare",
    "match": "compare",
    "versus": "compare",
    "frame": "extract",
    "capture": "extract",
    "ocr": "extract",
    "keyframe": "extract",
    "isolate": "extract",
    "grab": "extract",
}


@tool(name="perception", large_output=True)
async def perception_tool(
    action: Annotated[
        Literal["analyze", "transcribe", "compare", "extract"],
        "The action to perform. Supported values: analyze, transcribe, compare, extract.",
    ],
    source: Annotated[
        str | None, "Primary media file path or URL. Required for analyze, transcribe, extract actions."
    ] = None,
    sources: Annotated[list | None, "Multiple file paths or URLs. Required for compare action (2+ items)."] = None,
    question: Annotated[str | None, "Question to answer about the media content. Omit for a general summary."] = None,
    sample_rate: Annotated[float | None, "Video frame sampling rate in fps. Optional, defaults to 1.0."] = None,
    start_time: Annotated[float | None, "Video analysis start time in seconds. Optional."] = None,
    end_time: Annotated[float | None, "Video analysis end time in seconds. Optional."] = None,
    target_time: Annotated[
        int | None, "Target time in seconds for keyframe extraction. Required for extract action."
    ] = None,
    window_size: Annotated[
        int | None, "Window around target_time for keyframe extraction in seconds. Defaults to 5."
    ] = None,
    output_dir: Annotated[str | None, "Output directory for extracted keyframes. Optional for extract action."] = None,
) -> dict:
    """Analyze images, videos, and audio — answer questions, transcribe, compare, or extract frames.

    <instructions>
    - Media type is auto-detected from the file extension or URL pattern.
    - Supported image formats: .png, .jpg, .jpeg, .gif, .webp, .bmp, .svg.
    - Supported video formats: .mp4, .avi, .mov, .mkv, .webm, or YouTube URLs.
    - Supported audio formats: .mp3, .wav, .ogg, .flac, .m4a, .aac.
    - Use `analyze` to understand and answer questions about a single media file. Omit `question` for a general summary.
    - Use `transcribe` to extract text from audio (speech-to-text) or YouTube videos (captions).
    - Use `compare` to compare multiple images or videos side by side and answer a question about differences or similarities.
    - Use `extract` to pull keyframes from a video around a specific timestamp for detailed examination.
    - For video analysis, adjust `sample_rate` to control the number of frames examined per second.
    - After every two perception operations, MUST save key findings to text files to prevent loss of multimodal information.
    </instructions>

    <recommended_usage>
    - Use `analyze` to understand the content of images, videos, or audio files.
    - Use `analyze` with a specific `question` for targeted information extraction from media.
    - Use `transcribe` to convert speech in audio or video files to text.
    - Use `compare` to identify differences between multiple images or video clips.
    - Use `extract` to capture specific moments from a video for closer inspection.
    </recommended_usage>
    """
    action, _alias = resolve_alias(action, _PERCEPTION_ALIASES)

    try:
        from .media import (
            _analyze_local_video,
            _analyze_youtube_video,
            _audio_question_answering,
            _audio_transcription,
            _compare_multiple_videos,
            _extract_keyframes,
            _summarize_local_video,
            _transcribe_youtube_video,
        )
        from .vision import _compare_multiple_images, _visual_question_answering

        # Refresh environment variables on each call
        get_tool_env()

        if action == "analyze":
            if not source:
                return error_result(
                    "Missing source",
                    error="source is required for analyze action",
                    hint="Provide a file path or URL via the source parameter",
                )
            media_type = _detect_media_type(source)
            if media_type == "image":
                return alias_hint(
                    await _visual_question_answering(source, question or "Describe this image in detail."),
                    _alias,
                    action,
                )
            elif media_type == "youtube":
                return alias_hint(
                    await _analyze_youtube_video(source, question or "Summarize this video."), _alias, action
                )
            elif media_type == "video":
                if question:
                    return alias_hint(
                        await _analyze_local_video(source, question, sample_rate or 1.0, start_time or 0.0, end_time),
                        _alias,
                        action,
                    )
                else:
                    return alias_hint(
                        await _summarize_local_video(source, sample_rate or 1, start_time or 0.0, end_time),
                        _alias,
                        action,
                    )
            elif media_type == "audio":
                return alias_hint(
                    await _audio_question_answering(source, question or "What is discussed in this audio?"),
                    _alias,
                    action,
                )
            else:
                return error_result(
                    "Unknown media type",
                    error=f"Cannot determine media type for: {source}",
                    hint="Supported extensions: images (.png, .jpg, .jpeg, .gif, .webp, .bmp, .svg), videos (.mp4, .avi, .mov, .mkv, .webm), audio (.mp3, .wav, .ogg, .flac, .m4a, .aac)",
                )

        elif action == "transcribe":
            if not source:
                return error_result(
                    "Missing source",
                    error="source is required for transcribe action",
                    hint="Provide a file path or URL via the source parameter",
                )
            media_type = _detect_media_type(source)
            if media_type == "youtube":
                return alias_hint(await _transcribe_youtube_video(source), _alias, action)
            else:
                return alias_hint(await _audio_transcription(source), _alias, action)

        elif action == "compare":
            if not sources or len(sources) < 2:
                return error_result(
                    "Missing sources",
                    error="sources list with 2+ items is required for compare action",
                    hint="Provide a list of 2-4 file paths or URLs via the sources parameter",
                )
            if not question:
                return error_result(
                    "Missing question",
                    error="question is required for compare action",
                    hint="Provide a question describing what to compare",
                )
            # detect from first source
            media_type = _detect_media_type(sources[0])
            if media_type in ("image",):
                return alias_hint(await _compare_multiple_images(sources, question), _alias, action)
            else:
                return alias_hint(
                    await _compare_multiple_videos(sources, question, sample_rate, start_time, end_time), _alias, action
                )

        elif action == "extract":
            if not source:
                return error_result(
                    "Missing source",
                    error="source is required for extract action",
                    hint="Provide a video file path via the source parameter",
                )
            if target_time is None:
                return error_result(
                    "Missing target_time",
                    error="target_time is required for extract action",
                    hint="Provide the target time in seconds via the target_time parameter",
                )
            return alias_hint(
                await _extract_keyframes(source, target_time, window_size or 5, output_dir), _alias, action
            )

        else:
            return error_result(
                "Invalid action",
                error=f"Unknown action: {action}",
                hint="Valid actions: analyze, transcribe, compare, extract",
            )
    except Exception as e:
        logger.exception("perception_tool error: %s", e)
        return error_result(
            f"Perception operation failed: {e}",
            hint="An unexpected error occurred. Check the media file path and API keys.",
        )


PERCEPTION_TOOLS = [perception_tool]
