"""
Expo (React Native) Mobile Project Manager

Provides a unified tool to manage Expo mobile projects including:
- Creating new Expo projects from templates
- Setting and listing workspace projects
- Running shell commands in project context
- Expo web development server management
- npm dependency installation
"""

__version__ = "0.1.0"

import atexit
import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Annotated, Literal, Optional

import git
from _lib.utils import alias_hint, error_result, resolve_alias
from _lib.validators import (
    ensure_git_config,
    validate_name,
    validate_port,
)
from exo import tool
from git_ops import set_project_path as _set_git_project_path

# ============================================================================
# Configuration Constants
# ============================================================================

DEFAULT_SHUTDOWN_TIMEOUT = 5
DEFAULT_NPM_TIMEOUT = 300  # 5 minutes for npm operations

# Resolve bundled skills directory (tools/ → sandbox/skills/)
_SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


def _load_skill(skill_name: str) -> str:
    """Read a bundled skill.md and return its content, or empty string on failure."""
    skill_path = _SKILLS_DIR / skill_name / "skill.md"
    try:
        return skill_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning(f"Could not load skill '{skill_name}': {e}")
        return ""


# ============================================================================
# Environment Configuration
# ============================================================================
MOBILE_TEMPLATE_PATH = os.getenv("MOBILE_TEMPLATE_PATH", "./templates")
WORKSPACE_PATH = os.getenv("WORKSPACE", "./workspace")

# Global state for tracking current project and server process
current_project_path: Optional[Path] = None
server_process: Optional[subprocess.Popen] = None
server_port: Optional[int] = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("template-manager")


def get_tool_env():
    global MOBILE_TEMPLATE_PATH, WORKSPACE_PATH
    MOBILE_TEMPLATE_PATH = os.getenv("MOBILE_TEMPLATE_PATH", "./templates")
    WORKSPACE_PATH = os.getenv("WORKSPACE", "./workspace")
    return {"MOBILE_TEMPLATE_PATH": MOBILE_TEMPLATE_PATH, "WORKSPACE_PATH": WORKSPACE_PATH}


# ============================================================================
# Resource Cleanup
# ============================================================================
def cleanup_resources() -> None:
    """Clean up all resources on exit."""
    global server_process, server_port

    if server_process is not None and server_process.poll() is None:
        logger.info("Cleaning up: stopping development server...")
        try:
            if platform.system() != "Windows":
                try:
                    os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    pass
            else:
                server_process.terminate()

            try:
                server_process.wait(timeout=DEFAULT_SHUTDOWN_TIMEOUT)
                logger.info("Development server stopped gracefully")
            except subprocess.TimeoutExpired:
                logger.warning("Graceful shutdown timed out, forcing kill...")
                try:
                    if platform.system() != "Windows":
                        os.killpg(os.getpgid(server_process.pid), signal.SIGKILL)
                    else:
                        server_process.kill()
                except (ProcessLookupError, OSError):
                    pass
                server_process.wait()
                logger.info("Development server force killed")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        finally:
            server_process = None
            server_port = None


# Register cleanup handler
atexit.register(cleanup_resources)


# ============================================================================
# Helper Functions
# ============================================================================
def _load_env() -> None:
    """Reload environment variables from system environment."""
    global MOBILE_TEMPLATE_PATH, WORKSPACE_PATH
    MOBILE_TEMPLATE_PATH = os.getenv("MOBILE_TEMPLATE_PATH", "./templates")
    WORKSPACE_PATH = os.getenv("WORKSPACE", "./workspace")


def get_current_project() -> Path:
    """Get the current project path or raise error if not set."""
    if current_project_path is None:
        raise ValueError(
            "No current project set. "
            "Hint: Use set_current_project('project-name') to select an existing project, "
            "or copy_template('template-name', 'project-name') to create a new one. "
            "Use list_projects() to see available projects."
        )
    if not current_project_path.exists():
        raise ValueError(
            f"Current project path '{current_project_path}' no longer exists. "
            "Hint: The project may have been deleted. Use list_projects() to see available projects."
        )
    return current_project_path


def get_available_templates():
    """Get list of available templates."""
    base_path = Path(MOBILE_TEMPLATE_PATH)
    if not base_path.exists():
        return []
    return [d.name for d in base_path.iterdir() if d.is_dir()]


# ============================================================================
# Internal action implementations
# ============================================================================


def _init_project(name: str, title: str, description: str) -> str:
    """Copy the Expo template to the workspace and set it as the current project."""
    get_tool_env()
    _load_env()
    global current_project_path

    try:
        validate_name(name, "name")
    except ValueError as e:
        return f"Error: {str(e)}"

    template_path = Path(MOBILE_TEMPLATE_PATH)

    workspace = Path(WORKSPACE_PATH)
    workspace.mkdir(parents=True, exist_ok=True)

    project_path = workspace / name
    if project_path.exists():
        return (
            f"Error: Project '{name}' already exists at {project_path}.\n"
            f"Hint: Choose a different project name, or use mobile_project(action='set', name='{name}') "
            f"to work with the existing project."
        )

    try:
        shutil.copytree(
            template_path, project_path, ignore=shutil.ignore_patterns(".git", "node_modules", ".expo", "dist")
        )

        # Update project metadata
        _write_project_metadata(project_path, name, title, description)

        # Write sandbox-meta.json so expose_port can auto-detect framework/kind
        try:
            (project_path / ".sandbox-meta.json").write_text(
                json.dumps(
                    {
                        "framework": "expo",
                        "kind": "expo-web",
                        "template": "expo-mobile-template",
                    }
                )
            )
        except OSError as e:
            logger.warning(f"Failed to write .sandbox-meta.json: {e}")

        # Verify sandbox-selector client was vendored with the template
        if not (project_path / "lib" / "sandbox-selector.ts").exists():
            logger.warning(
                f"sandbox-selector.ts missing from {project_path}/lib/ — "
                "component selector overlay will not be available in web dev mode"
            )

        current_project_path = project_path
        _set_git_project_path(current_project_path)

        repo = git.Repo.init(project_path)
        ensure_git_config(repo)
        repo.index.add("*")
        repo.index.commit("Initial commit - Template copied")

        env_example = project_path / ".env.example"
        env_local = project_path / ".env.local"
        if env_example.exists() and not env_local.exists():
            shutil.copy(env_example, env_local)

        # Install npm dependencies
        npm_result = subprocess.run(
            ["npm", "install"], cwd=str(project_path), capture_output=True, text=True, timeout=DEFAULT_NPM_TIMEOUT
        )
        if npm_result.returncode != 0:
            logger.warning(f"npm install had issues: {npm_result.stderr}")

        result = (
            f"Expo app created at {project_path}\n"
            f"Current project set to: {name}\n"
            f"Git repository initialized\n"
            f"Dependencies installed\n"
            f"Environment file created: .env.local\n"
            f"Loaded skill: mobiledev"
        )

        skill_content = _load_skill("mobiledev")
        if skill_content:
            result += f"\n\n---\n\n{skill_content}"

        return result

    except PermissionError as e:
        return (
            f"Error: Permission denied while setting up Expo project.\n"
            f"Details: {str(e)}\n"
            f"Hint: Check that you have write permissions to {WORKSPACE_PATH}"
        )
    except subprocess.TimeoutExpired:
        return (
            f"Expo project created at {project_path} but npm install timed out.\n"
            f"Hint: Run action='install_deps' to retry dependency installation."
        )
    except OSError as e:
        return (
            f"Error: File system error while copying Expo project.\n"
            f"Details: {str(e)}\n"
            f"Hint: Check available disk space and file permissions."
        )
    except Exception as e:
        logger.exception(f"Unexpected error copying template: {e}")
        return f"Error copying template: {str(e)}"


def _write_project_metadata(project_path: Path, name: str, title: str, description: str) -> None:
    """Write project name, title, and description into package.json and app.json."""
    # Update package.json
    package_json_path = project_path / "package.json"
    if package_json_path.exists():
        try:
            with open(package_json_path, "r", encoding="utf-8") as f:
                pkg = json.load(f)
            pkg["name"] = name
            if description:
                pkg["description"] = description
            with open(package_json_path, "w", encoding="utf-8") as f:
                json.dump(pkg, f, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not update package.json: {e}")

    # Update app.json (Expo config)
    app_json_path = project_path / "app.json"
    if app_json_path.exists():
        try:
            with open(app_json_path, "r", encoding="utf-8") as f:
                app_config = json.load(f)
            if "expo" in app_config:
                app_config["expo"]["name"] = title or name
                app_config["expo"]["slug"] = name
                if description:
                    app_config["expo"]["description"] = description
            with open(app_json_path, "w", encoding="utf-8") as f:
                json.dump(app_config, f, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not update app.json: {e}")


def _set_project(project_name: str) -> str:
    """Set an existing project as the current project."""
    get_tool_env()
    _load_env()
    global current_project_path

    try:
        validate_name(project_name, "project_name")
    except ValueError as e:
        return f"Error: {str(e)}"

    workspace = Path(WORKSPACE_PATH)
    project_path = workspace / project_name

    if not project_path.exists():
        if workspace.exists():
            available = [d.name for d in workspace.iterdir() if d.is_dir()]
        else:
            available = []

        if available:
            return (
                f"Error: Project '{project_name}' not found.\n"
                f"Available projects: {', '.join(available)}\n"
                f"Hint: Check the spelling or use one of the available projects listed above."
            )
        else:
            return (
                f"Error: Project '{project_name}' not found.\n"
                f"No projects exist in workspace '{WORKSPACE_PATH}'.\n"
                f"Hint: Create a new project using action='init' with name='project-name'"
            )

    current_project_path = project_path
    _set_git_project_path(current_project_path)
    return f"Current project set to: {project_name} at {project_path}"


def _list_projects() -> str:
    """List all projects in the workspace."""
    get_tool_env()
    workspace = Path(WORKSPACE_PATH)
    if not workspace.exists():
        return "No workspace directory found. Create a project first."

    projects = [d.name for d in workspace.iterdir() if d.is_dir()]

    if not projects:
        return "No projects found in workspace."

    output = "Projects in workspace:\n\n"
    for project in projects:
        marker = "-> " if current_project_path and current_project_path.name == project else "   "
        output += f"{marker}{project}\n"

    return output


def _install_deps() -> str:
    """Install npm dependencies for the current project."""
    get_tool_env()
    try:
        project_path = get_current_project()

        package_json = project_path / "package.json"
        if not package_json.exists():
            return (
                "Error: package.json not found.\n"
                "This doesn't appear to be a Node.js project.\n"
                "Hint: Make sure you've selected the correct project."
            )

        logger.info(f"Running npm install in {project_path}")
        result = subprocess.run(
            ["npm", "install"], cwd=str(project_path), capture_output=True, text=True, timeout=DEFAULT_NPM_TIMEOUT
        )

        if result.returncode == 0:
            return (
                f"Dependencies installed successfully for {project_path.name}\n"
                f"{result.stdout[-500:] if len(result.stdout) > 500 else result.stdout}"
            )
        else:
            return (
                f"npm install completed with errors (exit code {result.returncode})\n"
                f"stderr: {result.stderr[-500:] if len(result.stderr) > 500 else result.stderr}\n"
                f"Hint: Check package.json for syntax errors or version conflicts."
            )

    except subprocess.TimeoutExpired:
        return "Error: npm install timed out after 5 minutes.\nHint: Check network connectivity or try again."
    except ValueError as e:
        return f"Error: {str(e)}"
    except FileNotFoundError:
        return "Error: npm not found.\nHint: Install Node.js and npm first. Visit https://nodejs.org/"
    except Exception as e:
        logger.exception(f"Error installing dependencies: {e}")
        return f"Error installing dependencies: {str(e)}"


def _start_server(port: int = 8080) -> str:
    """Start an Expo web development server for the current project."""
    get_tool_env()
    _load_env()
    global server_process, server_port

    try:
        validate_port(port)
    except ValueError as e:
        return f"Error: {str(e)}"

    try:
        project_path = get_current_project()

        # Check if npx is available
        try:
            npx_check = subprocess.run(["npx", "--version"], capture_output=True, text=True, timeout=10)
            if npx_check.returncode != 0:
                return (
                    "Error: npx command failed.\n"
                    "Hint: Make sure Node.js is properly installed and in your PATH.\n"
                    "Visit https://nodejs.org/ for installation instructions."
                )
        except FileNotFoundError:
            return (
                "Error: npx not found.\nHint: Install Node.js from https://nodejs.org/\nnpx is included with npm 5.2+."
            )
        except subprocess.TimeoutExpired:
            return "Error: npx command timed out. Please check your Node.js installation."

        # Check if node_modules exists
        node_modules = project_path / "node_modules"
        if not node_modules.exists():
            return "Error: node_modules not found.\nHint: Run action='install_deps' first, then try again."

        # Stop existing server if running
        if server_process is not None and server_process.poll() is None:
            logger.info(f"Stopping existing server on port {server_port}")
            try:
                if platform.system() != "Windows":
                    os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
                else:
                    server_process.terminate()

                server_process.wait(timeout=DEFAULT_SHUTDOWN_TIMEOUT)
            except (subprocess.TimeoutExpired, ProcessLookupError, OSError):
                try:
                    if platform.system() != "Windows":
                        os.killpg(os.getpgid(server_process.pid), signal.SIGKILL)
                    else:
                        server_process.kill()
                except (ProcessLookupError, OSError):
                    pass
            finally:
                server_process = None
                server_port = None

        # Check if port is already in use
        try:
            import socket

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(("localhost", port))
            sock.close()

            if result == 0:
                return (
                    f"Error: Port {port} is already in use.\n"
                    f"Hint: Choose a different port or stop the process using port {port}.\n"
                    f"Common alternative ports: 8080, 8081, 3000, 19006"
                )
        except Exception as e:
            logger.warning(f"Could not check port availability: {e}")

        logger.info(f"Starting Expo web server on port {port} at {project_path}")

        env = os.environ.copy()
        env["BROWSER"] = "none"  # Prevent Expo from opening browser automatically

        # Start Expo web server
        if platform.system() != "Windows":
            server_process = subprocess.Popen(
                ["npx", "expo", "start", "--web", "--port", str(port), "--host", "lan"],
                cwd=str(project_path),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=os.setsid,
            )
        else:
            server_process = subprocess.Popen(
                ["npx", "expo", "start", "--web", "--port", str(port), "--host", "lan"],
                cwd=str(project_path),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )

        server_port = port

        # Wait a moment to check if server started successfully
        time.sleep(2)

        if server_process.poll() is not None:
            stdout, stderr = server_process.communicate()
            server_process = None
            server_port = None
            return (
                f"Error: Expo dev server failed to start.\n"
                f"Details: {stderr if stderr else stdout}\n"
                f"Hint: Try running 'npx expo start --clear' to clear the Metro cache.\n"
                f"Check that your Expo project is properly configured."
            )

        return (
            f"Expo dev server started successfully\n"
            f"URL: http://localhost:{port}\n"
            f"Project: {project_path.name}\n"
            f"Server PID: {server_process.pid}\n\n"
            f"Tips:\n"
            f"   - Server will auto-stop when this script exits\n"
            f"   - Use action='stop_server' to manually stop\n"
            f"   - Check logs if the page doesn't load immediately\n"
            f"   - Hot reload is enabled - changes will reflect automatically"
        )

    except ValueError as e:
        return f"Error: {str(e)}"
    except PermissionError:
        return (
            f"Error: Permission denied to start server on port {port}.\n"
            f"Hint: Ports below 1024 require elevated permissions. Try a port >= 1024."
        )
    except Exception as e:
        logger.exception(f"Error starting Expo dev server: {e}")
        server_process = None
        server_port = None
        return f"Error starting Expo dev server: {str(e)}"


def _stop_server() -> str:
    """Stop the currently running Expo web development server."""
    get_tool_env()
    global server_process, server_port

    if server_process is None:
        return "No Expo dev server is currently running.\nHint: Use action='start_server' to start a server."

    if server_process.poll() is not None:
        server_process = None
        server_port = None
        return "Expo dev server was already stopped."

    try:
        old_port = server_port
        logger.info(f"Stopping Expo dev server on port {server_port}")

        if platform.system() != "Windows":
            try:
                os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
        else:
            server_process.terminate()

        try:
            server_process.wait(timeout=DEFAULT_SHUTDOWN_TIMEOUT)
            server_process = None
            server_port = None
            return f"Expo dev server stopped successfully\nPort {old_port} is now available"
        except subprocess.TimeoutExpired:
            logger.warning("Graceful shutdown timed out, forcing kill")
            try:
                if platform.system() != "Windows":
                    os.killpg(os.getpgid(server_process.pid), signal.SIGKILL)
                else:
                    server_process.kill()
            except (ProcessLookupError, OSError):
                pass

            server_process.wait()
            server_process = None
            server_port = None
            return f"Expo dev server force stopped\nHad to force kill the process\nPort {old_port} is now available"

    except Exception as e:
        logger.exception(f"Error stopping server: {e}")
        server_process = None
        server_port = None
        return f"Error stopping server: {str(e)}"


def _restart_server(port: int | None = None) -> str:
    """Restart the Expo dev server, optionally on a new port."""
    get_tool_env()
    restart_port = port or server_port or 8080

    stop_msg = _stop_server()
    start_msg = _start_server(restart_port)
    return f"{stop_msg}\n\n{start_msg}"


def _server_status() -> str:
    """Get the status of the Expo web development server."""
    get_tool_env()
    global server_process, server_port

    if server_process is None:
        return "No Expo dev server is running\nHint: Use action='start_server' to start one."

    if server_process.poll() is not None:
        server_process = None
        server_port = None
        return (
            "Expo dev server has stopped\n"
            "The process terminated unexpectedly.\n"
            "Hint: Check logs and restart with action='start_server'."
        )

    return (
        f"Expo dev server is running\n"
        f"URL: http://localhost:{server_port}\n"
        f"PID: {server_process.pid}\n"
        f"Project: {current_project_path.name if current_project_path else 'Unknown'}"
    )


# ============================================================================
# Mobile Tools (split by function)
# ============================================================================


@tool(name="mobile_init")
async def mobile_init_tool(
    brief: Annotated[str, "A one-sentence description of the project initialization purpose."],
    name: Annotated[str, "Name of the mobile project to be created (used as directory name)."],
    title: Annotated[str, "Title of the mobile project (used as display name in app)."],
    description: Annotated[str, "Description of the mobile project."],
) -> str:
    """Initialize a new mobile app project with scaffold, automated environment setup and hosting services.

    <instructions>
    - Always init project first before making detailed plans; there's a lot of information that can be learned after the project is initialized.
    - Creates scaffolding under the workspace with automated environment setup.
    - Initializes git repo, installs dependencies, and sets up .env.local.
    - DO NOT use parallel processing in mobile development projects.
    </instructions>

    <recommended_usage>
    - Use for native iOS/Android applications built with Expo (React Native).
    </recommended_usage>
    """
    try:
        return _init_project(name, title, description)
    except Exception as e:
        logger.exception("mobile_init_tool error: %s", e)
        return error_result(
            f"Mobile init failed: {e}", hint="An unexpected error occurred during project initialization."
        )


_MOBILE_PROJECT_ALIASES: dict[str, str] = {
    "switch": "set",
    "select": "set",
    "activate": "set",
    "choose": "set",
    "pick": "set",
    "use": "set",
    "show": "list",
    "display": "list",
    "ls": "list",
    "view": "list",
    "available": "list",
}


@tool(name="mobile_project")
async def mobile_project_tool(
    action: Annotated[
        Literal["set", "list"], "The action to perform: 'set' to switch active project, 'list' to show all projects."
    ],
    name: Annotated[str | None, "Project name. Required for 'set' action."] = None,
) -> str:
    """Manage mobile projects in the workspace — switch between or list projects.

    <instructions>
    - Use 'set' to switch the active project context.
    - Use 'list' to see all available projects in the workspace.
    </instructions>
    """
    action, _alias = resolve_alias(action, _MOBILE_PROJECT_ALIASES)

    try:
        if action == "set":
            if not name:
                return error_result(
                    "'name' is required for 'set' action.", hint="Use action='set' with name='project_name'."
                )
            return alias_hint(_set_project(name), _alias, action)
        elif action == "list":
            return alias_hint(_list_projects(), _alias, action)
        else:
            return error_result(f"Unknown action '{action}'.", hint="Valid actions: set, list.")
    except Exception as e:
        logger.exception("mobile_project_tool error: %s", e)
        return error_result(f"Mobile project operation failed: {e}", hint="An unexpected error occurred.")


_MOBILE_SERVER_ALIASES: dict[str, str] = {
    "run": "start",
    "launch": "start",
    "begin": "start",
    "boot": "start",
    "serve": "start",
    "halt": "stop",
    "kill": "stop",
    "terminate": "stop",
    "shutdown": "stop",
    "end": "stop",
    "reboot": "restart",
    "reload": "restart",
    "reset": "restart",
    "cycle": "restart",
    "check": "status",
    "info": "status",
    "state": "status",
    "health": "status",
    "install": "install_deps",
    "deps": "install_deps",
    "setup": "install_deps",
    "npm_install": "install_deps",
    "dependencies": "install_deps",
}


@tool(name="mobile_server")
async def mobile_server_tool(
    action: Annotated[Literal["start", "stop", "restart", "status", "install_deps"], "Server action to perform."],
    port: Annotated[int | None, "Expo dev server port. Optional for start and restart. Defaults to 8080."] = None,
) -> str:
    """Manage the Expo development server lifecycle and dependencies.

    <instructions>
    - Use 'start' to launch the Expo web development server for preview.
    - Use 'install_deps' to install or update project dependencies.
    - Use 'status' to check if the server is running.
    - Use 'stop' to shut down the running server.
    - Use 'restart' to stop and start the server, optionally on a new port.
    </instructions>
    """
    action, _alias = resolve_alias(action, _MOBILE_SERVER_ALIASES)

    try:
        if action == "start":
            return alias_hint(_start_server(port=port or 8080), _alias, action)
        elif action == "stop":
            return alias_hint(_stop_server(), _alias, action)
        elif action == "restart":
            return alias_hint(_restart_server(port=port), _alias, action)
        elif action == "status":
            return alias_hint(_server_status(), _alias, action)
        elif action == "install_deps":
            return alias_hint(_install_deps(), _alias, action)
        else:
            return error_result(
                f"Unknown action '{action}'.", hint="Valid actions: start, stop, restart, status, install_deps."
            )
    except Exception as e:
        logger.exception("mobile_server_tool error: %s", e)
        return error_result(f"Mobile server operation failed: {e}", hint="An unexpected error occurred.")


MOBILE_TOOLS = [mobile_init_tool, mobile_project_tool, mobile_server_tool]
