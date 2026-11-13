"""
Video analysis and audio transcription functions for the perception tool.
"""

import asyncio
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests
from _lib.utils import error_result, success_result

from .tool import (
    AUDIO_LLM_MODEL_PROVIDER,
    VIDEO_ANALYZE_PROMPT,
    VIDEO_SUMMARIZE_PROMPT,
    VISION_LLM_API_KEY,
    VISION_LLM_BASE_URL,
    VISION_LLM_MODEL_NAME,
    VISION_LLM_MODEL_PROVIDER,
    WORKSPACE,
    _get_anthropic_cls,
    _get_audio_model,
    _get_audio_openai_client,
    _get_audio_transcription_model,
    _get_openai_classes,
    create_video_content_for_llm,
    encode_audio_file,
    extract_keyframes_with_scene_detection,
    get_audio_duration,
    get_audio_extension,
    get_video_frames,
    save_keyframes,
)


async def _transcribe_youtube_video(url: str) -> dict:
    """Transcribe the audio and describe the visuals of a YouTube video."""
    # YouTube transcription requires Gemini
    return error_result(
        "YouTube transcription is currently disabled",
        hint="This feature requires Gemini which has been archived. Use scrape_website to get video subtitles/descriptions instead.",
    )

    # --- Original Gemini implementation (see git history) ---


async def _analyze_youtube_video(url: str, question: str) -> dict:
    """Answer a question about a YouTube video's audiovisual content."""
    # YouTube video analysis requires Gemini
    return error_result(
        "YouTube video analysis is currently disabled",
        hint="This feature requires Gemini which has been archived. Use scrape_website to get video subtitles/descriptions instead.",
    )

    # --- Original Gemini implementation (see git history) ---


async def _analyze_local_video(
    video_path: str,
    question: str,
    sample_rate: float = 1.0,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    max_workers: int = 4,
) -> dict:
    """Analyze local video content using AI with parallel processing."""
    start_exec_time = time.time()

    try:
        if not os.path.exists(video_path):
            return error_result(
                "Analysis failed",
                error=f"[ERROR]: Video file not found: {video_path}",
                hint="The video file does not exist at the given path. Use the find tool to locate it, or check that the path is absolute.",
            )

        # Extract video frames
        video_frames = get_video_frames(video_path, int(sample_rate), start_time, end_time)

        # Process frames in chunks for parallel analysis
        chunk_size = 128
        chunks = []

        for i in range(0, len(video_frames), chunk_size):
            chunk_frames = video_frames[i : i + chunk_size]
            chunks.append((i // chunk_size, chunk_frames, question))

        all_results = [None] * len(chunks)

        def analyze_chunk(chunk_data):
            chunk_index, frames, q = chunk_data
            try:
                content = create_video_content_for_llm(
                    VIDEO_ANALYZE_PROMPT.format(task=q), frames, VISION_LLM_MODEL_PROVIDER
                )

                # Call appropriate LLM based on provider
                if VISION_LLM_MODEL_PROVIDER == "anthropic":
                    client = _get_anthropic_cls()(api_key=VISION_LLM_API_KEY, base_url=VISION_LLM_BASE_URL)
                    response = client.messages.create(
                        model=VISION_LLM_MODEL_NAME,
                        max_tokens=4096,
                        messages=[{"role": "user", "content": content}],
                    )
                    result = response.content[0].text
                elif VISION_LLM_MODEL_PROVIDER == "azure_openai":
                    client = _get_openai_classes()[1](
                        api_key=VISION_LLM_API_KEY,
                        api_version=os.getenv("AZURE_OPENAI_API_VERSION", ""),
                        azure_endpoint=VISION_LLM_BASE_URL,
                    )
                    response = client.chat.completions.create(
                        model=VISION_LLM_MODEL_NAME,
                        max_tokens=4096,
                        messages=[{"role": "user", "content": content}],
                    )
                    result = response.choices[0].message.content
                elif VISION_LLM_MODEL_PROVIDER == "openai":
                    client = _get_openai_classes()[0](api_key=VISION_LLM_API_KEY, base_url=VISION_LLM_BASE_URL)
                    response = client.chat.completions.create(
                        model=VISION_LLM_MODEL_NAME,
                        max_tokens=4096,
                        messages=[{"role": "user", "content": content}],
                    )
                    result = response.choices[0].message.content
                else:
                    result = f"Unsupported vision provider: {VISION_LLM_MODEL_PROVIDER}"

                return chunk_index, result
            except Exception as e:
                return chunk_index, f"Analysis failed for video segment {chunk_index + 1}: {str(e)}"

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(analyze_chunk, chunk): chunk[0] for chunk in chunks}

            for future in as_completed(futures):
                try:
                    chunk_index, result = future.result()
                    all_results[chunk_index] = f"Result of video part {chunk_index + 1}: {result}"
                except Exception as e:
                    chunk_index = futures[future]
                    all_results[chunk_index] = f"Result of video part {chunk_index + 1}: Analysis failed - {str(e)}"

        analysis_result = "\n".join([r for r in all_results if r is not None])
        duration_analyzed = end_time - start_time if end_time else len(video_frames) / sample_rate
        execution_time = time.time() - start_exec_time

        return success_result(
            "Analysis complete",
            result=f"""# Video Analysis Results

## Video Information
**Source:** `{video_path}`
**Frames Analyzed:** {len(video_frames)}
**Duration:** {duration_analyzed:.2f} seconds
**Chunks Processed:** {len(chunks)}
**Execution Time:** {execution_time:.2f}s

## Analysis Results
{analysis_result}
""",
        )

    except Exception as e:
        execution_time = time.time() - start_exec_time
        return error_result(
            "Analysis failed",
            error=f"[ERROR]: Video analysis failed: {str(e)}\nExecution time: {execution_time:.2f}s",
            hint="Video analysis failed. Ensure the video file is a supported format (.mp4, .avi, .mov, .mkv, .webm) and is not corrupted. Check that cv2 (OpenCV) is installed.",
        )


async def _summarize_local_video(
    video_path: str,
    sample_rate: int = 1,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
) -> dict:
    """Summarize the main content of a local video using AI analysis."""
    start_exec_time = time.time()

    try:
        if not os.path.exists(video_path):
            return error_result(
                "Analysis failed",
                error=f"[ERROR]: Video file not found: {video_path}",
                hint="The video file does not exist at the given path. Use the find tool to locate it, or check that the path is absolute.",
            )

        video_frames = get_video_frames(video_path, sample_rate, start_time, end_time)

        interval = 490
        frame_nums = 500
        all_results = []

        for i in range(0, len(video_frames), interval):
            cur_frames = video_frames[i : i + frame_nums]
            content = create_video_content_for_llm(VIDEO_SUMMARIZE_PROMPT, cur_frames, VISION_LLM_MODEL_PROVIDER)

            try:
                if VISION_LLM_MODEL_PROVIDER == "anthropic":
                    client = _get_anthropic_cls()(api_key=VISION_LLM_API_KEY, base_url=VISION_LLM_BASE_URL)
                    response = client.messages.create(
                        model=VISION_LLM_MODEL_NAME,
                        max_tokens=4096,
                        messages=[{"role": "user", "content": content}],
                    )
                    cur_summary = response.content[0].text
                elif VISION_LLM_MODEL_PROVIDER == "azure_openai":
                    client = _get_openai_classes()[1](
                        api_key=VISION_LLM_API_KEY,
                        api_version=os.getenv("AZURE_OPENAI_API_VERSION", ""),
                        azure_endpoint=VISION_LLM_BASE_URL,
                    )
                    response = client.chat.completions.create(
                        model=VISION_LLM_MODEL_NAME,
                        max_tokens=4096,
                        messages=[{"role": "user", "content": content}],
                    )
                    cur_summary = response.choices[0].message.content
                elif VISION_LLM_MODEL_PROVIDER == "openai":
                    client = _get_openai_classes()[0](api_key=VISION_LLM_API_KEY, base_url=VISION_LLM_BASE_URL)
                    response = client.chat.completions.create(
                        model=VISION_LLM_MODEL_NAME,
                        max_tokens=4096,
                        messages=[{"role": "user", "content": content}],
                    )
                    cur_summary = response.choices[0].message.content
                else:
                    cur_summary = f"Unsupported vision provider: {VISION_LLM_MODEL_PROVIDER}"
            except Exception as e:
                cur_summary = f"Summary failed for video segment {i // interval + 1}: {str(e)}"

            all_results.append(f"Summary of video part {i // interval + 1}: {cur_summary}")

            if i + frame_nums >= len(video_frames):
                break

        summary_result = "\n".join(all_results)
        duration_analyzed = end_time - start_time if end_time else len(video_frames) / sample_rate
        execution_time = time.time() - start_exec_time

        return success_result(
            "Analysis complete",
            result=f"""# Video Summary

## Video Information
**Source:** `{video_path}`
**Frames Analyzed:** {len(video_frames)}
**Duration:** {duration_analyzed:.2f} seconds
**Execution Time:** {execution_time:.2f}s

## Summary
{summary_result}
""",
        )

    except Exception as e:
        execution_time = time.time() - start_exec_time
        return error_result(
            "Analysis failed",
            error=f"[ERROR]: Video summarization failed: {str(e)}\nExecution time: {execution_time:.2f}s",
            hint="Video summarization failed. Ensure the video file is a supported format (.mp4, .avi, .mov, .mkv, .webm) and the vision LLM API key is set.",
        )


async def _extract_keyframes(
    video_path: str,
    target_time: int,
    window_size: int = 5,
    output_dir: Optional[str] = None,
) -> dict:
    """Extract key frames around a target time with scene detection."""
    start_exec_time = time.time()

    try:
        if not os.path.exists(video_path):
            return error_result(
                "Analysis failed",
                error=f"[ERROR]: Video file not found: {video_path}",
                hint="The video file does not exist at the given path. Use the find tool to locate it, or check that the path is absolute.",
            )

        output_dir = str(WORKSPACE / "keyframes") if output_dir is None else output_dir
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        frames, frame_times = extract_keyframes_with_scene_detection(video_path, target_time, window_size)

        frame_paths, frame_timestamps = save_keyframes(frames, frame_times, str(output_path))

        execution_time = time.time() - start_exec_time

        result_parts = [
            "# Keyframe Extraction Results",
            "",
            "## Extraction Parameters",
            f"**Target Time:** {target_time}s",
            f"**Window Size:** {window_size}s",
            f"**Frames Extracted:** {len(frame_paths)}",
            f"**Output Directory:** `{output_path}`",
            f"**Execution Time:** {execution_time:.2f}s",
            "",
            "## Extracted Frames",
        ]

        for i, (path, timestamp) in enumerate(zip(frame_paths, frame_timestamps), 1):
            result_parts.append(f"{i}. `{path}` (at {timestamp:.2f}s)")

        return success_result("Analysis complete", result="\n".join(result_parts))

    except Exception as e:
        execution_time = time.time() - start_exec_time
        return error_result(
            "Analysis failed",
            error=f"[ERROR]: Keyframe extraction failed: {str(e)}\nExecution time: {execution_time:.2f}s",
            hint="Keyframe extraction failed. Ensure cv2 (OpenCV) is installed and the video file is a supported format (.mp4, .avi, .mov, .mkv, .webm).",
        )


async def _compare_multiple_videos(
    video_paths: list[str],
    question: str,
    sample_rate: float = 1.0,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
) -> dict:
    """Compare and analyze multiple videos (2-4) with citations."""
    if not (2 <= len(video_paths) <= 4):
        return error_result(
            "Analysis failed",
            error="[ERROR]: Please provide between 2 and 4 videos for comparison.",
            hint="The compare action requires between 2 and 4 videos in the sources list.",
        )

    start_exec_time = time.time()

    try:
        # Verify all video files exist
        for i, path in enumerate(video_paths, 1):
            if not os.path.exists(path):
                return error_result(
                    "Analysis failed",
                    error=f"[ERROR]: Video {i} not found: {path}",
                    hint="Use the find tool to locate the correct video path, or verify the file exists at the given location.",
                )

        # Extract frames from all videos
        all_video_frames = []
        video_metadata = []

        for i, video_path in enumerate(video_paths, 1):
            frames = get_video_frames(video_path, int(sample_rate), start_time, end_time)
            all_video_frames.append(frames)
            video_metadata.append({"number": i, "path": video_path, "frame_count": len(frames)})

        # Build prompt with citation instructions
        comparison_prompt = f"""You are analyzing multiple videos simultaneously. For each observation or claim you make,
you MUST cite which video(s) support it using the format [Video N] where N is the video number (1, 2, 3, or 4).

Videos are numbered as follows:
{chr(10).join([f"- Video {v['number']}: {v['path']} ({v['frame_count']} frames analyzed)" for v in video_metadata])}

Question: {question}

IMPORTANT:
- Always cite sources with [Video N] format
- If an observation applies to multiple videos, cite all relevant ones: [Video 1, Video 2]
- Be specific about which video shows what
- Compare and contrast content, actions, scenes, and temporal sequences across videos
- Consider differences in pacing, style, and content

The frames from each video will be presented in sequence. Analyze them carefully and provide your comparative analysis with proper citations:"""

        # Build content for LLM
        if VISION_LLM_MODEL_PROVIDER == "anthropic":
            content = [{"type": "text", "text": comparison_prompt}]

            for i, frames in enumerate(all_video_frames, 1):
                # Add marker for video
                content.append({"type": "text", "text": f"\n=== Video {i} Frames ==="})
                # Sample frames to avoid token limits (max ~30 frames per video)
                step = max(1, len(frames) // 30)
                for frame in frames[::step]:
                    parts = frame["data"].split(",")
                    image_format = parts[0].split(":")[1].split(";")[0]
                    frame_data_only = parts[1]
                    content.append(
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": image_format, "data": frame_data_only},
                        }
                    )

            client = _get_anthropic_cls()(api_key=VISION_LLM_API_KEY, base_url=VISION_LLM_BASE_URL)
            response = client.messages.create(
                model=VISION_LLM_MODEL_NAME, max_tokens=4096, messages=[{"role": "user", "content": content}]
            )
            result = response.content[0].text

        elif VISION_LLM_MODEL_PROVIDER in ["openai", "azure_openai"]:
            content = [{"type": "text", "text": comparison_prompt}]

            for i, frames in enumerate(all_video_frames, 1):
                content.append({"type": "text", "text": f"\n=== Video {i} Frames ==="})
                step = max(1, len(frames) // 30)
                for frame in frames[::step]:
                    content.append({"type": "image_url", "image_url": {"url": frame["data"]}})

            if VISION_LLM_MODEL_PROVIDER == "azure_openai":
                client = _get_openai_classes()[1](
                    api_key=VISION_LLM_API_KEY,
                    api_version=os.getenv("AZURE_OPENAI_API_VERSION", ""),
                    azure_endpoint=VISION_LLM_BASE_URL,
                )
            else:
                client = _get_openai_classes()[0](api_key=VISION_LLM_API_KEY, base_url=VISION_LLM_BASE_URL)

            response = client.chat.completions.create(
                model=VISION_LLM_MODEL_NAME, messages=[{"role": "user", "content": content}]
            )
            result = response.choices[0].message.content

        else:
            return error_result(
                "Analysis failed",
                error=f"Unsupported vision provider: {VISION_LLM_MODEL_PROVIDER}",
                hint="Supported providers: anthropic, openai, azure_openai.",
            )

        execution_time = time.time() - start_exec_time
        total_frames = sum(v["frame_count"] for v in video_metadata)

        video_list = "\n".join(
            [f"- Video {v['number']}: `{v['path']}` ({v['frame_count']} frames)" for v in video_metadata]
        )

        return success_result(
            "Analysis complete",
            result=f"""# Multi-Video Comparison Results

## Videos Analyzed
{video_list}

## Analysis Parameters
**Sample Rate:** {sample_rate} fps
**Time Range:** {start_time}s - {end_time if end_time else "end"}
**Total Frames Analyzed:** {total_frames}
**Execution Time:** {execution_time:.2f}s

## Comparative Analysis with Citations
{result}

---
Note: Citations like [Video 1] refer to the videos listed above.""",
        )

    except Exception as e:
        execution_time = time.time() - start_exec_time
        return error_result(
            "Analysis failed",
            error=f"[ERROR]: Multi-video comparison failed: {str(e)}\nExecution time: {execution_time:.2f}s",
            hint="Multi-video comparison failed. Verify all video paths exist and are supported formats (.mp4, .avi, .mov, .mkv, .webm).",
        )


async def _audio_transcription(audio_path: str) -> dict:
    """Transcribe audio file to text using a specialised LLM."""
    max_retries = 3
    retry = 0
    transcription = None
    if audio_path == "":
        return error_result(
            "Empty audio path", error="audio_path is empty", hint="Provide a valid file path or URL to an audio file"
        )

    if AUDIO_LLM_MODEL_PROVIDER is None:
        return error_result(
            "No LLM provider configured",
            error="LLM_MODEL_PROVIDER is not set",
            hint="Set a default LLM for audio from Midsphere UI > Settings > Agent > LLM",
        )

    while retry < max_retries:
        try:
            client = _get_audio_openai_client()
            if os.path.exists(audio_path):  # Check if the file exists locally
                with open(audio_path, "rb") as audio_file:
                    transcription = client.audio.transcriptions.create(
                        model=_get_audio_transcription_model(), file=audio_file
                    )
            else:
                # download the audio file from the URL
                response = requests.get(audio_path)
                response.raise_for_status()  # Raise an exception for bad status codes

                # Basic content validation - check if response has content
                if not response.content:
                    raise Exception("Downloaded file is empty.")

                # Check content type if available
                content_type = response.headers.get("content-type", "").lower()

                # Get proper extension for the temporary file
                file_extension = get_audio_extension(audio_path, content_type)

                # Use proper temporary file handling with correct extension
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                    temp_file.write(response.content)
                    temp_audio_path = temp_file.name

                try:
                    with open(temp_audio_path, "rb") as audio_file:
                        transcription = client.audio.transcriptions.create(
                            model=_get_audio_transcription_model(), file=audio_file
                        )
                finally:
                    # Clean up the temp file
                    if os.path.exists(temp_audio_path):
                        os.remove(temp_audio_path)
            break

        except requests.RequestException as e:
            retry += 1
            if retry >= max_retries:
                return error_result(
                    "Audio transcription failed: could not download audio file",
                    error=str(e),
                    hint="Verify audio file path and API key. URLs must be publicly accessible (no YouTube). Supported formats: MP3, WAV, M4A.",
                )
            await asyncio.sleep(5 * (2**retry))
        except Exception as e:
            return error_result(
                "Audio transcription failed",
                error=str(e),
                hint="Verify audio file path and API key. Supported formats: MP3, WAV, M4A.",
            )

    return success_result("Transcription complete", transcription=transcription.text)


async def _audio_question_answering(audio_path_or_url: str, question: str) -> dict:
    """Answer the question based on the given audio information."""
    temp_audio_path: str | None = None
    try:
        if audio_path_or_url == "":
            return error_result(
                "Empty audio path",
                error="audio_path_or_url is empty",
                hint="Provide a valid file path or URL to an audio file",
            )

        if AUDIO_LLM_MODEL_PROVIDER is None:
            return error_result(
                "No LLM provider configured",
                error="LLM_MODEL_PROVIDER is not set",
                hint="Set a default LLM for audio from Midsphere UI > Settings > Agent > LLM",
            )

        client = _get_audio_openai_client()

        text_prompt = f"""Answer the following question based on the given audio information:\n\n{question}"""

        is_local_audio = True
        if os.path.exists(audio_path_or_url):  # Check if the file exists locally
            encoded_string, file_format = encode_audio_file(audio_path_or_url)
            duration = get_audio_duration(audio_path_or_url)
        else:
            # download the audio file from the URL
            response = requests.get(
                audio_path_or_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                },
            )
            response.raise_for_status()  # Raise an exception for bad status codes

            # Basic content validation - check if response has content
            if not response.content:
                return error_result(
                    "Downloaded file is empty",
                    error="response.content is empty",
                    hint="Use a local file path or a publicly accessible URL to a supported audio format (MP3, WAV, M4A)",
                )

            # Check content type if available
            content_type = response.headers.get("content-type", "").lower()

            # Get proper extension for the temporary file
            file_extension = get_audio_extension(audio_path_or_url, content_type)

            # Use proper temporary file handling with correct extension
            with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
                temp_file.write(response.content)
                temp_audio_path = temp_file.name

            is_local_audio = False
            encoded_string, file_format = encode_audio_file(temp_audio_path)
            duration = get_audio_duration(temp_audio_path)

        if encoded_string is None or file_format is None:
            return error_result(
                "Failed to encode audio file",
                error="encoded_string or file_format is None",
                hint="Use a local file path or a publicly accessible URL to a supported audio format (MP3, WAV, M4A)",
            )

        response = client.chat.completions.create(
            model=_get_audio_model(),
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant specializing in audio analysis.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text_prompt},
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": encoded_string,
                                "format": file_format,
                            },
                        },
                    ],
                },
            ],
        )
    except Exception as e:
        return error_result(
            "Audio question answering failed",
            error=str(e),
            hint="Verify audio file path and API key. Supported formats: MP3, WAV, M4A.",
        )
    finally:
        if temp_audio_path and os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)

    answer = response.choices[0].message.content
    return success_result("Audio question answered", answer=answer, duration_seconds=duration)
