"""
Vision (image) analysis functions for the perception tool.
"""

import base64
import os

from _lib.utils import error_result, success_result

from .tool import (
    OCR_PROMPT,
    VISION_LLM_API_KEY,
    VISION_LLM_BASE_URL,
    VISION_LLM_MODEL_NAME,
    VISION_LLM_MODEL_PROVIDER,
    VQA_PROMPT,
    _get_anthropic_cls,
    _get_openai_classes,
    call_claude_vision,
    call_openai_vision,
    detect_image_format,
)


async def _visual_question_answering(image_path_or_url: str, question: str) -> dict:
    """Ask questions about an image with vision models and automatic OCR."""
    ocr_prompt = OCR_PROMPT
    if VISION_LLM_MODEL_PROVIDER == "anthropic":
        ocr_result = await call_claude_vision(image_path_or_url, ocr_prompt)
    elif VISION_LLM_MODEL_PROVIDER == "azure_openai":
        ocr_result = await call_openai_vision(image_path_or_url, ocr_prompt)
    elif VISION_LLM_MODEL_PROVIDER == "openai":
        ocr_result = await call_openai_vision(image_path_or_url, ocr_prompt)
    else:
        return error_result(
            "Analysis failed",
            error="[ERROR]: No API key is set, visual_question_answering tool is not available.",
            hint="Set MANAGED_VISION_LLM_API_KEY or LLM_API_KEY environment variable. Configure vision LLM from Midsphere UI > Settings > Agent > LLM.",
        )

    vqa_prompt = VQA_PROMPT.format(ocr_result=ocr_result, question=question)

    if VISION_LLM_MODEL_PROVIDER == "anthropic":
        vqa_result = await call_claude_vision(image_path_or_url, vqa_prompt)
    elif VISION_LLM_MODEL_PROVIDER == "azure_openai":
        vqa_result = await call_openai_vision(image_path_or_url, vqa_prompt)
    elif VISION_LLM_MODEL_PROVIDER == "openai":
        vqa_result = await call_openai_vision(image_path_or_url, vqa_prompt)
    else:
        return error_result(
            "Analysis failed",
            error="[ERROR]: No API key is set, visual_question_answering tool is not available.",
            hint="Set MANAGED_VISION_LLM_API_KEY or LLM_API_KEY environment variable. Configure vision LLM from Midsphere UI > Settings > Agent > LLM.",
        )

    return success_result("Analysis complete", result=f"OCR results:\n{ocr_result}\n\nVQA result:\n{vqa_result}")


async def _compare_multiple_images(image_paths_or_urls: list[str], question: str) -> dict:
    """Compare and analyze multiple images (2-4) with citations."""
    if not (2 <= len(image_paths_or_urls) <= 4):
        return error_result(
            "Analysis failed",
            error="[ERROR]: Please provide between 2 and 4 images for comparison.",
            hint="The compare action requires between 2 and 4 images in the sources list.",
        )

    if VISION_LLM_MODEL_PROVIDER not in ["anthropic", "openai", "azure_openai"]:
        return error_result(
            "Analysis failed",
            error="[ERROR]: No API key is set, compare_multiple_images tool is not available.",
            hint="Set MANAGED_VISION_LLM_API_KEY or LLM_API_KEY environment variable. Configure vision LLM from Midsphere UI > Settings > Agent > LLM.",
        )

    try:
        # Build prompt with citation instructions
        comparison_prompt = f"""You are analyzing multiple images simultaneously. For each observation or claim you make,
you MUST cite which image(s) support it using the format [Image N] where N is the image number (1, 2, 3, or 4).

Images are numbered in the order they appear in this conversation:
- Image 1: First image
- Image 2: Second image
- Image 3: Third image (if provided)
- Image 4: Fourth image (if provided)

Question: {question}

IMPORTANT:
- Always cite sources with [Image N] format
- If an observation applies to multiple images, cite all relevant ones: [Image 1, Image 2]
- Be specific about which image shows what
- Compare and contrast across images where relevant

Provide your analysis with proper citations:"""

        # Build content for LLM based on provider
        if VISION_LLM_MODEL_PROVIDER == "anthropic":
            content = [{"type": "text", "text": comparison_prompt}]
            for i, img_path in enumerate(image_paths_or_urls, 1):
                if os.path.exists(img_path):
                    with open(img_path, "rb") as f:
                        image_data = base64.b64encode(f.read()).decode("utf-8")
                    content.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": await detect_image_format(img_path),
                                "data": image_data,
                            },
                        }
                    )
                else:
                    url = img_path if img_path.startswith("https://") else f"https://{img_path}"
                    content.append({"type": "image", "source": {"type": "url", "url": url}})

            client = _get_anthropic_cls()(api_key=VISION_LLM_API_KEY, base_url=VISION_LLM_BASE_URL)
            response = client.messages.create(
                model=VISION_LLM_MODEL_NAME, max_tokens=4096, messages=[{"role": "user", "content": content}]
            )
            result = response.content[0].text

        elif VISION_LLM_MODEL_PROVIDER in ["openai", "azure_openai"]:
            content = [{"type": "text", "text": comparison_prompt}]
            for img_path in image_paths_or_urls:
                if os.path.exists(img_path):
                    with open(img_path, "rb") as f:
                        image_data = base64.b64encode(f.read()).decode("utf-8")
                    mime_type = await detect_image_format(img_path)
                    content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}})
                else:
                    content.append({"type": "image_url", "image_url": {"url": img_path}})

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
                error="[ERROR]: Unsupported vision provider.",
                hint="Supported providers: anthropic, openai, azure_openai.",
            )

        # Format the result with image list
        image_list = "\n".join([f"- Image {i}: `{path}`" for i, path in enumerate(image_paths_or_urls, 1)])

        return success_result(
            "Analysis complete",
            result=f"""# Multi-Image Analysis Results

## Images Analyzed
{image_list}

## Analysis with Citations
{result}

---
Note: Citations like [Image 1] refer to the images listed above.""",
        )

    except Exception as e:
        return error_result(
            "Analysis failed",
            error=f"[ERROR]: Multi-image analysis failed: {str(e)}",
            hint="Multi-image analysis failed. Verify all image paths exist and are supported formats (.png, .jpg, .jpeg, .gif, .webp, .bmp, .svg).",
        )
