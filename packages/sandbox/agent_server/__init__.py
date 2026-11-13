"""Sukuna Agent Server — lightweight Django project.

Usage:
    python -m agent_server [--port PORT]
    uvicorn agent_server.asgi:application
"""

default_app_config = "agent_server.apps.AgentServerConfig"
