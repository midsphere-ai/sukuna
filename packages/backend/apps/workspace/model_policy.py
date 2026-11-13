"""Org-level model policy enforcement.

Checks whether a requested model/provider is permitted by the organization's
model policy before an agent run starts. Returns structured error info or None.
"""

import logging

logger = logging.getLogger(__name__)


def check_org_model_policy(conv, user, requested_model: str | None) -> dict | None:
    """Check org model policy for a conversation's project context.

    Returns a dict with error info if the model is blocked, or None if allowed.
    Personal runs (no project or no org) are never blocked.
    The returned dict has keys: 'detail', 'allowed_models', 'allowed_providers'.
    """
    project = getattr(conv, "project", None)
    if project is None:
        return None

    org = getattr(project, "organization", None)
    if org is None:
        return None

    from apps.workspace.models import OrgModelPolicy

    try:
        policy = org.model_policy
    except OrgModelPolicy.DoesNotExist:
        return None

    if not requested_model:
        # No explicit model requested — platform default is always allowed
        return None

    # Parse model string: could be "provider:model" or just "model"
    if ":" in requested_model:
        provider, model_name = requested_model.split(":", 1)
    else:
        provider = None
        model_name = requested_model

    # Check allowed_providers (non-empty = explicit allow list)
    if policy.allowed_providers and provider:
        if provider not in policy.allowed_providers:
            return {
                "detail": f"Provider '{provider}' not permitted by organization policy.",
                "allowed_models": policy.allowed_models or [],
                "allowed_providers": policy.allowed_providers or [],
            }

    # Check allowed_models (non-empty = explicit allow list)
    if policy.allowed_models:
        if (
            model_name not in policy.allowed_models
            and requested_model not in policy.allowed_models
        ):
            return {
                "detail": f"Model '{model_name}' not permitted by organization policy.",
                "allowed_models": policy.allowed_models,
                "allowed_providers": policy.allowed_providers or [],
            }

    return None


def should_block_byom(conv) -> bool:
    """Check if BYOM is blocked for the conversation's org project.

    Returns True if the org has a model policy with block_byom=True.
    Personal runs (no project or no org) never block BYOM.
    """
    project = getattr(conv, "project", None)
    if project is None:
        return False

    org = getattr(project, "organization", None)
    if org is None:
        return False

    from apps.workspace.models import OrgModelPolicy

    try:
        policy = org.model_policy
    except OrgModelPolicy.DoesNotExist:
        return False

    return policy.block_byom
