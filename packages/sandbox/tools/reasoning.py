"""Extended-thinking reasoning tool — delegates complex analysis to a dedicated LLM call."""

__version__ = "0.1.0"

import asyncio
import logging
import os
from typing import Annotated, Literal

from _lib.utils import alias_hint, error_result, resolve_alias, success_result
from exo import tool
from pydantic.fields import FieldInfo

logger = logging.getLogger(__name__)


# ========================
# API KEYS
# ========================
LLM_API_KEY = os.environ.get("MANAGED_REASONING_LLM_API_KEY") or os.environ.get("LLM_API_KEY")
LLM_BASE_URL = os.environ.get("MANAGED_REASONING_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL", "")
LLM_MODEL_NAME = os.environ.get("MANAGED_REASONING_LLM_MODEL") or os.environ.get("LLM_MODEL_NAME")
LLM_MODEL_PROVIDER = os.environ.get("MANAGED_REASONING_LLM_PROVIDER") or os.environ.get("LLM_MODEL_PROVIDER")
LLM_MODEL_TEMPERATURE = os.environ.get("LLM_MODEL_TEMPERATURE")
_CLIENT_CACHE: dict[tuple[str, str | None, str | None], object] = {}


def get_tool_env():
    global LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, LLM_MODEL_PROVIDER, LLM_MODEL_TEMPERATURE

    LLM_API_KEY = os.environ.get("MANAGED_REASONING_LLM_API_KEY") or os.environ.get("LLM_API_KEY")
    LLM_BASE_URL = os.environ.get("MANAGED_REASONING_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL", "")
    LLM_MODEL_NAME = os.environ.get("MANAGED_REASONING_LLM_MODEL") or os.environ.get("LLM_MODEL_NAME")
    LLM_MODEL_PROVIDER = os.environ.get("MANAGED_REASONING_LLM_PROVIDER") or os.environ.get("LLM_MODEL_PROVIDER")
    LLM_MODEL_TEMPERATURE = os.environ.get("LLM_MODEL_TEMPERATURE")


# ========================
# MCP HELPERS
# ========================

GUARD_PROMPT = (
    "## Your Role\n"
    "You are an expert at identifying the potential loopholes or oversights"
    "of the current reasoning process while solving the complex problem.\n\n "
    "## Your Task: \n"
    "Based on the gathered information retrieved from the internet, and the reasoning process already"
    "generated towards solving a complex task, you need to do the following 1 or 2 things, to guarntee the quality of the reasoning process, and a clear final answer: \n"
    "  1. Provide your diagnosing result on the generated reasoning process and the corresponding the correction if necessary;\n"
    "  2. Provide your insight and supplements in advance to avoid the potential loopholes or oversights in the future;\n\n"
    "## Requirements: \n"
    "  1. If the reasoning process already generated is complete and correct in your opinion, just say 'No loopholes or oversights found'. \n"
    "  2. If the reasoning process already generated contains the materials that may lead to the potential logic mistake or lack of some important guardrails in your opinion, you may give a hint to the current reasoning process, with the necessary supplements.\n"
    "  3. If the reasoning process already generated is seriously incorrect in your opinion, you may give the turn signal to the reasoning process, to maneuver the reasoning process towards solving the complex problem correctly. \n\n"
    "## Restriction: \n"
    "  1. Please do not make judgments about the authenticity of externally sourced information obtained through searches, as this is not part of your job responsibilities;\n"
    "  2. Do not make additional inferences or assumptions about the content of such information itself.\n"
    "  3. If the question lacks necessary details/data/clues in your opinion, you may ask for more details.\n\n"
    "## Example 1:\n"
    "  Question: Is my reasoning process correct?\n"
    "  Reasoning Process: (nothing specified)\n"
    "  Your Identification Result: Your question lacks some information, please provide me more details so I can help you.\n\n"
)

REASONING_PROMPT = (
    "You are an expert at solving complex problems including math, "
    "code contests, riddles, and puzzles. "
    "Provide detailed step-by-step reasoning and a clear final answer."
)


def prepare_reasoning_prompt(question: str, original_task: str = "") -> str:
    """Prepare the reasoning prompt with question and optional context.

    Args:
        question: The main question for reasoning
        original_task: Optional original task description for context

    Returns:
        Formatted prompt string
    """
    if original_task:
        return f"Original Task: {original_task}\n\nQuestion: {question}"
    return f"Question: {question}"


def get_llm_client_and_model():
    if LLM_MODEL_PROVIDER == "azure_openai":
        from openai import AzureOpenAI

        cache_key = ("azure_openai", LLM_API_KEY, LLM_BASE_URL)
        client = _CLIENT_CACHE.get(cache_key)
        if client is None:
            client = AzureOpenAI(
                api_key=LLM_API_KEY,
                api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
                azure_endpoint=LLM_BASE_URL,
            )
            _CLIENT_CACHE[cache_key] = client
        return client, LLM_MODEL_NAME, "azure_openai"
    elif LLM_MODEL_PROVIDER == "openai":
        from openai import OpenAI

        cache_key = ("openai", LLM_API_KEY, LLM_BASE_URL)
        client = _CLIENT_CACHE.get(cache_key)
        if client is None:
            client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
            _CLIENT_CACHE[cache_key] = client
        return client, LLM_MODEL_NAME, "openai"
    elif LLM_MODEL_PROVIDER == "anthropic":
        from anthropic import Anthropic

        cache_key = ("anthropic", LLM_API_KEY, LLM_BASE_URL)
        client = _CLIENT_CACHE.get(cache_key)
        if client is None:
            client = Anthropic(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
            _CLIENT_CACHE[cache_key] = client
        return client, LLM_MODEL_NAME, "anthropic"
    elif LLM_MODEL_PROVIDER == "gemini":
        return None, LLM_MODEL_NAME, "gemini"
    return None, None, None


async def _call_llm_with_retry(messages: list, max_retries: int = 1, temperature: float = 0.3) -> str:
    """Shared function to call LLM with retry logic for both OpenAI and Anthropic."""

    client, model_name, provider = get_llm_client_and_model()

    if not provider:
        return "[ERROR]: No valid LLM provider configured (Azure, OpenAI, or Anthropic)."

    if provider in ["openai", "azure_openai"]:
        for attempt in range(1, max_retries + 1):
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=temperature,
                    extra_body={},
                )
                content = response.choices[0].message.content

                if content and content.strip():
                    return content
                else:
                    if attempt >= max_retries:
                        return f"Reasoning ({provider} Client) failed after {max_retries} retries: Empty response received\n"
                    await asyncio.sleep(5 * (2**attempt))
                    continue

            except Exception as e:
                if attempt >= max_retries:
                    return f"Reasoning ({provider} Client) failed after {max_retries} retries: {e}\n"
                await asyncio.sleep(5 * (2**attempt))
    elif provider == "anthropic":
        # Anthropic
        for attempt in range(1, max_retries + 1):
            try:
                response = client.messages.create(
                    model=model_name,
                    max_tokens=21000,
                    thinking={
                        "type": "enabled",
                        "budget_tokens": 19000,
                    },
                    messages=messages,
                    temperature=temperature,
                    stream=False,
                )
                content = response.content[-1].text

                if content and content.strip():
                    return content
                else:
                    if attempt >= max_retries:
                        return f"[ERROR]: Reasoning (Anthropic Client) failed after {max_retries} retries: Empty response received\n"
                    await asyncio.sleep(5 * (2**attempt))
                    continue

            except Exception as e:
                if attempt >= max_retries:
                    return f"[ERROR]: Reasoning (Anthropic Client) failed after {max_retries} retries: {e}\n"
                await asyncio.sleep(5 * (2**attempt))
    elif "gemini" in provider:
        # Assuming it's gemini at the end
        for attempt in range(1, max_retries + 1):
            try:
                from openai import OpenAI

                client = OpenAI(
                    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                    api_key=LLM_API_KEY,
                )
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    extra_body={},
                )
                content = response.choices[0].message.content
                if content and content.strip():
                    return content
                else:
                    if attempt >= max_retries:
                        return f"[ERROR]: Reasoning (Gemini Client) failed after {max_retries} retries: Empty response received\n"
                    await asyncio.sleep(5 * (2**attempt))
                    continue

            except Exception as e:
                if attempt >= max_retries:
                    return f"[ERROR]: Reasoning (Gemini Client) failed after {max_retries} retries: {e}\n"
                await asyncio.sleep(5 * (2**attempt))
    else:
        return "[ERROR]: No valid provider found"


def _handle_field_info(*fields):
    """Extract default values from FieldInfo objects."""
    return tuple(f.default if isinstance(f, FieldInfo) else f for f in fields)


# ========================
# INTERNAL FUNCTIONS
# ========================


async def _complex_reasoning(
    question: str,
    original_task: str = "",
    temperature: float = 0.3,
    reasoning_style: str = "detailed",
) -> dict:
    """Perform complex reasoning on a problem using a secondary LLM call."""

    # Handle FieldInfo objects
    question, original_task, temperature, reasoning_style = _handle_field_info(
        question, original_task, temperature, reasoning_style
    )

    # Validate input
    if not question or not question.strip():
        return error_result(
            "Question is required for complex problem reasoning.", hint="Provide a non-empty question parameter."
        )

    # Prepare the reasoning prompt
    prompt = prepare_reasoning_prompt(question, original_task)

    # Enhance prompt based on reasoning style
    style_prompts = {
        "step-by-step": "\n\nPlease provide a clear step-by-step breakdown of your reasoning process.",
        "concise": "\n\nPlease provide a concise but complete reasoning and final answer.",
        "detailed": "\n\nPlease provide detailed analysis with comprehensive reasoning.",
    }
    prompt += style_prompts.get(reasoning_style, "")

    # Prepare messages
    messages_for_llm = [
        {"role": "system", "content": REASONING_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt,
                }
            ],
        },
    ]

    result = await _call_llm_with_retry(messages_for_llm, temperature=temperature)
    if isinstance(result, str) and result.startswith("[ERROR]"):
        return error_result(
            "Reasoning failed",
            error=result,
            hint="The reasoning LLM call failed. Verify MANAGED_REASONING_LLM_API_KEY (or LLM_API_KEY), LLM_MODEL_NAME, and LLM_MODEL_PROVIDER are set. Configure from Midsphere UI > Settings > Agent > LLM.",
        )
    return success_result("Reasoning complete", result=result)


async def _guard_reasoning(
    question: str,
    original_task: str = "",
    temperature: float = 0.1,
    guarding_style: str = "detailed",
) -> dict:
    """Guard and validate the reasoning process for correctness and completeness."""

    # Handle FieldInfo objects
    question, original_task, temperature, guarding_style = _handle_field_info(
        question, original_task, temperature, guarding_style
    )

    # Validate input
    if not question or not question.strip():
        return error_result(
            "Question is required for guarding the complex problem reasoning process.",
            hint="Provide a non-empty question parameter.",
        )

    # Prepare the guarding prompt
    prompt = prepare_reasoning_prompt(question, original_task)

    # Enhance prompt based on guarding style
    style_prompts = {
        "step-by-step": "\n\nPlease provide a clear step-by-step breakdown of your reviewing process of the reasoning process.",
        "concise": "\n\nPlease provide a concise and final guarding answer.",
        "detailed": "\n\nPlease provide detailed reviewing analysis with comprehensive guarding.",
    }
    prompt += style_prompts.get(guarding_style, "")

    # Prepare messages
    messages_for_llm = [
        {
            "role": "system",
            "content": GUARD_PROMPT,
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt,
                }
            ],
        },
    ]

    result = await _call_llm_with_retry(messages_for_llm, temperature=temperature)
    if isinstance(result, str) and result.startswith("[ERROR]"):
        return error_result(
            "Guard reasoning failed",
            error=result,
            hint="The guard LLM call failed. Verify MANAGED_REASONING_LLM_API_KEY (or LLM_API_KEY), LLM_MODEL_NAME, and LLM_MODEL_PROVIDER are set. Configure from Midsphere UI > Settings > Agent > LLM.",
        )

    return success_result("Guard reasoning complete", result=result)


# ========================
# UNIFIED TOOL
# ========================

_REASONING_ALIASES: dict[str, str] = {
    "think": "reason",
    "analyze": "reason",
    "solve": "reason",
    "explain": "reason",
    "deduce": "reason",
    "infer": "reason",
    "validate": "guard",
    "check": "guard",
    "verify": "guard",
    "review": "guard",
    "assess": "guard",
    "evaluate": "guard",
}


@tool(name="reasoning")
async def reasoning_tool(
    action: Annotated[Literal["reason", "guard"], "The action to perform. Supported values: reason, guard."],
    question: Annotated[str, "The question or problem to reason about."],
    original_task: Annotated[str, "Context about the original task."] = "",
    temperature: Annotated[float, "LLM temperature for reasoning. Defaults to 0.3 for reason, 0.1 for guard."] = 0.3,
    style: Annotated[
        str, "Reasoning style. Supported values: detailed, concise, step-by-step. Defaults to detailed."
    ] = "detailed",
) -> dict:
    """Perform deep reasoning or validate existing reasoning using a secondary LLM call.

    <instructions>
    - Use this tool for complex problem-solving that benefits from extended thinking (math, logic, code analysis, multi-step deduction).
    - Use `reason` action to break down and solve complex problems step by step.
    - Use `guard` action to validate existing reasoning for completeness, bias, or logical errors.
    - NEVER use this tool for simple questions that can be answered directly.
    - Provide `original_task` context to help the reasoning model understand the broader goal.
    - Lower temperature produces more focused and deterministic reasoning; higher temperature allows more creative exploration.
    </instructions>

    <recommended_usage>
    - Use `reason` for complex mathematical calculations or proofs.
    - Use `reason` for multi-step logical deduction or analysis.
    - Use `reason` for in-depth code analysis or debugging complex issues.
    - Use `guard` to verify the correctness of a proposed solution before implementing it.
    - Use `guard` to check for edge cases, bias, or logical flaws in reasoning.
    </recommended_usage>
    """
    action, _alias = resolve_alias(action, _REASONING_ALIASES)

    try:
        if action == "reason":
            return alias_hint(
                await _complex_reasoning(
                    question=question, original_task=original_task, temperature=temperature, reasoning_style=style
                ),
                _alias,
                action,
            )
        elif action == "guard":
            # Guard uses lower temperature by default
            guard_temp = temperature if temperature != 0.3 else 0.1
            return alias_hint(
                await _guard_reasoning(
                    question=question, original_task=original_task, temperature=guard_temp, guarding_style=style
                ),
                _alias,
                action,
            )
        else:
            return error_result(f"Unknown action '{action}'.", hint="Valid actions: 'reason', 'guard'.")
    except Exception as e:
        logger.exception("reasoning_tool error: %s", e)
        return error_result(
            f"Reasoning operation failed: {e}", hint="An unexpected error occurred. Check LLM API keys and try again."
        )


REASONING_TOOLS = [reasoning_tool]
