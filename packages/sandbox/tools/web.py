"""
Next.js Web Project Manager

Provides a unified ``webdev`` tool to manage Next.js projects:
- Copying templates to workspace
- Managing environment variables
- SQLite database queries
- Web server management
- Dependency installation and shell commands

Requirements:
    pip install python-dotenv gitpython psutil

Configuration:
    Set TEMPLATE_BASE_PATH and WORKSPACE_PATH in environment
"""

__version__ = "0.1.0"

import atexit
import json
import logging
import os
import platform
import re
import shutil
import signal
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Annotated, List, Literal, Optional

import git
from _lib.utils import alias_hint, error_result, resolve_alias
from _lib.validators import (
    ensure_git_config,
    validate_env_filename,
    validate_name,
    validate_port,
)
from dotenv import set_key, unset_key
from exo import tool
from git_ops import set_project_path as _set_git_project_path

# ============================================================================
# Configuration Constants
# ============================================================================
DEFAULT_NPM_TIMEOUT = 300  # 5 minutes for npm operations
DEFAULT_DB_TIMEOUT = 30  # 30 seconds for database operations
DEFAULT_SHUTDOWN_TIMEOUT = 5  # 5 seconds for graceful shutdown
MAX_SQL_RESULT_ROWS = 1000  # Maximum rows to return from SQL queries
DEFAULT_EXPO_PORT = 8081

# Scaffold type → template directory name (under TEMPLATE_BASE_PATH)
SCAFFOLD_TEMPLATE_MAP = {
    "web-static": "websites/landing-page-template",
    "web-db-user": "websites/webapp-template",
    "web-db-supabase": "websites/webapp-supabase-template",
}

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
TEMPLATE_BASE_PATH = os.getenv("TEMPLATE_BASE_PATH", "./templates")
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
def get_tool_env() -> dict:
    """Reload environment variables from system environment."""
    global TEMPLATE_BASE_PATH, WORKSPACE_PATH
    TEMPLATE_BASE_PATH = os.getenv("TEMPLATE_BASE_PATH", "./templates")
    WORKSPACE_PATH = os.getenv("WORKSPACE", "./workspace")

    return {"TEMPLATE_BASE_PATH": TEMPLATE_BASE_PATH, "WORKSPACE_PATH": WORKSPACE_PATH}


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


def get_available_templates() -> List[str]:
    """Get list of available templates."""
    base_path = Path(TEMPLATE_BASE_PATH)
    if not base_path.exists():
        return []
    return [d.name for d in base_path.iterdir() if d.is_dir()]


# ============================================================================
# Internal action implementations
# ============================================================================


def _init_project(name: str, title: str, description: str, scaffold: str) -> str:
    """Copy a template to the workspace and set it as the current project."""
    get_tool_env()
    global current_project_path

    # Validate inputs
    try:
        validate_name(name, "name")
    except ValueError as e:
        return f"Error: {str(e)}"

    # Resolve scaffold to template directory
    template_dir = SCAFFOLD_TEMPLATE_MAP.get(scaffold)
    if not template_dir:
        return error_result(
            f"Unknown scaffold '{scaffold}'.",
            hint=f"Valid scaffolds: {', '.join(SCAFFOLD_TEMPLATE_MAP.keys())}.",
        )

    template_path = Path(TEMPLATE_BASE_PATH) / template_dir
    if not template_path.exists():
        available = get_available_templates()
        if available:
            return (
                f"Error: Template for scaffold '{scaffold}' not found at '{template_dir}'.\n"
                f"Available templates: {', '.join(available)}\n"
                f"Hint: Check that the template directory matches SCAFFOLD_TEMPLATE_MAP."
            )
        else:
            return (
                f"Error: Template for scaffold '{scaffold}' not found.\n"
                f"No templates available in {TEMPLATE_BASE_PATH}.\n"
                f"Hint: Check that TEMPLATE_BASE_PATH is set correctly and contains template directories."
            )

    # Create workspace if it doesn't exist
    workspace = Path(WORKSPACE_PATH)
    workspace.mkdir(parents=True, exist_ok=True)

    # Create project path
    project_path = workspace / name
    if project_path.exists():
        return (
            f"Error: Project '{name}' already exists at {project_path}.\n"
            f"Hint: Choose a different project name, or use web_project(action='set', name='{name}') "
            f"to work with the existing project."
        )

    try:
        # Copy template (don't copy git directories to avoid conflicts)
        shutil.copytree(template_path, project_path, ignore=shutil.ignore_patterns(".git", "node_modules", ".next"))

        # Update project metadata
        _write_project_metadata(project_path, name, title, description)

        # Write sandbox-meta.json so expose_port can auto-detect framework/kind
        try:
            (project_path / ".sandbox-meta.json").write_text(
                json.dumps(
                    {
                        "framework": "next",
                        "kind": "web",
                        "template": template_dir,
                    }
                )
            )
        except OSError as e:
            logger.warning(f"Failed to write .sandbox-meta.json: {e}")

        # Verify sandbox-selector client was vendored with the template
        if not (project_path / "lib" / "sandbox-selector.ts").exists():
            logger.warning(
                f"sandbox-selector.ts missing from {project_path}/lib/ — "
                "component selector overlay will not be available in dev mode"
            )

        # Set as current project
        current_project_path = project_path
        _set_git_project_path(current_project_path)

        # Initialize NEW git repository
        repo = git.Repo.init(project_path)
        ensure_git_config(repo)
        repo.index.add("*")
        repo.index.commit("Initial commit - Template copied")

        # Copy .env.example to .env.local if it exists
        env_example = project_path / ".env.example"
        env_local = project_path / ".env.local"
        if env_example.exists() and not env_local.exists():
            shutil.copy(env_example, env_local)

        subprocess.run(
            ["npm", "install"],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=DEFAULT_NPM_TIMEOUT,
        )

        if scaffold == "web-db-user":
            subprocess.run(
                ["npm", "run", "db:generate"],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=DEFAULT_NPM_TIMEOUT,
            )
            subprocess.run(
                ["npm", "run", "db:push"],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                timeout=DEFAULT_NPM_TIMEOUT,
            )

        result = (
            f"Web project '{name}' created at {project_path} (scaffold: {scaffold})\n"
            f"Current project set to: {name}\n"
            f"Git repository initialized\n"
            f"Dependencies installed\n"
            f"Environment file created: .env.local\n"
            f"Loaded skill: webdev"
        )

        skill_content = _load_skill("webdev")
        if skill_content:
            result += f"\n\n---\n\n{skill_content}"

        return result

    except PermissionError as e:
        return (
            f"Error: Permission denied while copying template.\n"
            f"Details: {str(e)}\n"
            f"Hint: Check that you have write permissions to {WORKSPACE_PATH}"
        )
    except OSError as e:
        return (
            f"Error: File system error while copying template.\n"
            f"Details: {str(e)}\n"
            f"Hint: Check available disk space and file permissions."
        )
    except Exception as e:
        logger.exception(f"Unexpected error copying template: {e}")
        return f"Error copying template: {str(e)}"


def _write_project_metadata(project_path: Path, name: str, title: str, description: str) -> None:
    """Write project name, title, and description into package.json."""
    package_json_path = project_path / "package.json"
    if package_json_path.exists():
        try:
            with open(package_json_path, "r", encoding="utf-8") as f:
                pkg = json.load(f)
            pkg["name"] = name
            if title:
                pkg["title"] = title
            if description:
                pkg["description"] = description
            with open(package_json_path, "w", encoding="utf-8") as f:
                json.dump(pkg, f, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not update package.json: {e}")


def _set_project(project_name: str) -> str:
    """Set an existing project as the current project."""
    get_tool_env()
    global current_project_path

    # Validate input
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
                f"Hint: Create a new project using copy_template('template-name', 'project-name')"
            )

    current_project_path = project_path
    _set_git_project_path(current_project_path)
    return f"Current project set to: {project_name} at {project_path}"


def _list_projects() -> str:
    """List all projects in the workspace."""
    workspace = Path(WORKSPACE_PATH)
    if not workspace.exists():
        return "No workspace directory found. Copy a template first."

    projects = [d.name for d in workspace.iterdir() if d.is_dir()]

    if not projects:
        return "No projects found in workspace."

    output = "Projects in workspace:\n\n"
    for project in projects:
        marker = "> " if current_project_path and current_project_path.name == project else "  "
        output += f"{marker}{project}\n"

    return output


def _add_env(key: str, value: str, env_file: str) -> str:
    """Add or update an environment variable in the current project."""
    get_tool_env()

    # Validate env_file to prevent path traversal
    try:
        validate_env_filename(env_file)
    except ValueError as e:
        return f"Error: {str(e)}"

    # Validate key
    if not key or not key.strip():
        return (
            "Error: Environment variable key cannot be empty.\n"
            "Hint: Use descriptive keys like 'DATABASE_URL', 'API_KEY', etc."
        )

    key = key.strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
        return (
            f"Error: Invalid environment variable key '{key}'.\n"
            "Keys must start with a letter or underscore, followed by letters, numbers, or underscores.\n"
            "Hint: Use names like 'DATABASE_URL', 'API_KEY', 'MY_VAR_123'"
        )

    try:
        project_path = get_current_project()
        env_path = project_path / env_file

        # Create env file if it doesn't exist
        if not env_path.exists():
            env_path.touch()
            logger.info(f"Created new env file: {env_file}")

        # Add or update the key
        set_key(str(env_path), key, value)

        return f"Environment variable '{key}' set in {env_file}"

    except ValueError as e:
        return f"Error: {str(e)}"
    except PermissionError:
        return f"Error: Permission denied writing to {env_file}.\nHint: Check file permissions for {env_path}"
    except Exception as e:
        logger.exception(f"Error adding environment variable: {e}")
        return f"Error adding environment variable: {str(e)}"


def _remove_env(key: str, env_file: str) -> str:
    """Remove an environment variable from the current project."""
    get_tool_env()

    # Validate env_file to prevent path traversal
    try:
        validate_env_filename(env_file)
    except ValueError as e:
        return f"Error: {str(e)}"

    # Validate key
    if not key or not key.strip():
        return "Error: Environment variable key cannot be empty.\nHint: Provide the key name you want to remove."

    key = key.strip()

    try:
        project_path = get_current_project()
        env_path = project_path / env_file

        if not env_path.exists():
            return (
                f"Error: {env_file} not found in project.\n"
                f"Hint: Available env files might be: .env, .env.local, .env.production\n"
                f"Use list_env_variables() to check existing env files."
            )

        # Remove the key - unset_key returns a tuple (success, key, value)
        result = unset_key(str(env_path), key)

        # unset_key returns (True, key, value) on success, (False, key, value) if key not found
        if result[0]:
            return f"Environment variable '{key}' removed from {env_file}"
        else:
            return (
                f"Warning: Key '{key}' was not found in {env_file}.\n"
                f"Hint: Use list_env_variables('{env_file}') to see existing variables."
            )

    except ValueError as e:
        return f"Error: {str(e)}"
    except PermissionError:
        return f"Error: Permission denied writing to {env_file}.\nHint: Check file permissions."
    except Exception as e:
        logger.exception(f"Error removing environment variable: {e}")
        return f"Error removing environment variable: {str(e)}"


def _list_env(env_file: str) -> str:
    """List all environment variables in the specified file."""
    get_tool_env()

    # Validate env_file to prevent path traversal
    try:
        validate_env_filename(env_file)
    except ValueError as e:
        return f"Error: {str(e)}"

    try:
        project_path = get_current_project()
        env_path = project_path / env_file

        if not env_path.exists():
            # List available env files
            env_files = [f.name for f in project_path.iterdir() if f.is_file() and f.name.startswith(".env")]
            if env_files:
                return (
                    f"No {env_file} file found.\n"
                    f"Available env files: {', '.join(env_files)}\n"
                    f"Hint: Try list_env_variables('{env_files[0]}')"
                )
            else:
                return (
                    f"No {env_file} file found.\n"
                    f"No .env files exist in the project.\n"
                    f"Hint: Create one using add_env_variable('KEY', 'value', '{env_file}')"
                )

        output = f"Environment variables in {env_file}:\n\n"
        var_count = 0

        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        # Partially hide value for security
                        if len(value) > 8:
                            hidden_value = value[:4] + "..." + value[-4:]
                        else:
                            hidden_value = "***"
                        output += f"  {key} = {hidden_value}\n"
                        var_count += 1

        if var_count == 0:
            output += "  (no variables defined)\n"
        else:
            output += f"\nTotal: {var_count} variable(s)"

        return output

    except ValueError as e:
        return f"Error: {str(e)}"
    except UnicodeDecodeError:
        return f"Error: Could not read {env_file} - file encoding issue.\nHint: Ensure the file is saved as UTF-8."
    except Exception as e:
        logger.exception(f"Error listing environment variables: {e}")
        return f"Error listing environment variables: {str(e)}"


def _execute_sql(query: str, fetch: bool) -> str:
    """Execute a SQL query on the current project's SQLite database."""
    get_tool_env()

    # Validate query
    if not query or not query.strip():
        return (
            "Error: SQL query cannot be empty.\nHint: Provide a valid SQL query, e.g., 'SELECT * FROM users LIMIT 10'"
        )

    query = query.strip()

    # Log the query for audit purposes (without values for security)
    query_type = query.split()[0].upper() if query.split() else "UNKNOWN"
    logger.info(f"Executing SQL query type: {query_type}")

    # Warn for destructive operations
    if query_type in ("DELETE", "DROP", "TRUNCATE", "ALTER"):
        logger.warning(f"Destructive SQL operation requested: {query_type}")

    try:
        project_path = get_current_project()
        db_path = project_path / "sqlite.db"

        if not db_path.exists():
            # Check for alternative database files
            db_files = [
                f.name for f in project_path.iterdir() if f.is_file() and f.suffix in (".db", ".sqlite", ".sqlite3")
            ]
            if db_files:
                return (
                    f"Error: sqlite.db not found, but found: {', '.join(db_files)}.\n"
                    f"Hint: This project may use a different database file."
                )
            return (
                "Error: sqlite.db not found.\n"
                "This project may not use SQLite, or the database hasn't been initialized yet.\n"
                "Hint: Run 'npm run db:push' in your project to create the database."
            )

        # Connect to database with timeout
        with sqlite3.connect(str(db_path), timeout=DEFAULT_DB_TIMEOUT) as conn:
            cursor = conn.cursor()

            try:
                cursor.execute(query)
            except sqlite3.OperationalError as e:
                error_str = str(e).lower()
                if "no such table" in error_str:
                    return f"SQLite error: {str(e)}\nHint: Use list_database_tables() to see available tables."
                elif "syntax error" in error_str:
                    return (
                        f"SQLite syntax error: {str(e)}\n"
                        f"Hint: Check your SQL syntax. Common issues include missing quotes or commas."
                    )
                raise

            if fetch:
                # Fetch results for SELECT queries with row limit
                results = cursor.fetchmany(MAX_SQL_RESULT_ROWS + 1)
                truncated = len(results) > MAX_SQL_RESULT_ROWS
                if truncated:
                    results = results[:MAX_SQL_RESULT_ROWS]

                columns = [description[0] for description in cursor.description] if cursor.description else []

                if not results:
                    return "Query executed successfully. No results returned."
                else:
                    output = f"Query Results ({len(results)} rows"
                    if truncated:
                        output += f", limited to {MAX_SQL_RESULT_ROWS}"
                    output += "):\n\n"

                    # Format as table
                    if columns:
                        output += "  " + " | ".join(columns) + "\n"
                        output += "  " + "-" * (len(" | ".join(columns))) + "\n"

                    for row in results:
                        output += "  " + " | ".join(str(val) for val in row) + "\n"

                    if truncated:
                        output += f"\nResults truncated to {MAX_SQL_RESULT_ROWS} rows. Add LIMIT to your query for specific counts."
            else:
                # Commit changes for INSERT/UPDATE/DELETE
                conn.commit()
                output = f"Query executed successfully. {cursor.rowcount} row(s) affected."

            return output

    except ValueError as e:
        return f"Error: {str(e)}"
    except sqlite3.OperationalError as e:
        return (
            f"SQLite operational error: {str(e)}\n"
            f"Hint: Database may be locked or corrupted. Try again or check if another process is using it."
        )
    except sqlite3.Error as e:
        return f"SQLite error: {str(e)}"
    except Exception as e:
        logger.exception(f"Error executing query: {e}")
        return f"Error executing query: {str(e)}"


def _list_tables() -> str:
    """List all tables in the current project's SQLite database."""
    get_tool_env()

    try:
        project_path = get_current_project()
        db_path = project_path / "sqlite.db"

        if not db_path.exists():
            # Check for alternative database files
            db_files = [
                f.name for f in project_path.iterdir() if f.is_file() and f.suffix in (".db", ".sqlite", ".sqlite3")
            ]
            if db_files:
                return (
                    f"Error: sqlite.db not found, but found: {', '.join(db_files)}.\n"
                    f"Hint: This project may use a different database file."
                )
            return (
                "Error: sqlite.db not found.\n"
                "Hint: Initialize the database with 'npm run db:push' or check TEMPLATE_BASE_PATH."
            )

        with sqlite3.connect(str(db_path), timeout=DEFAULT_DB_TIMEOUT) as conn:
            cursor = conn.cursor()

            # Get all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = cursor.fetchall()

            if not tables:
                return (
                    "No tables found in database.\n"
                    "Hint: The database exists but has no tables. Run 'npm run db:push' to create tables."
                )

            output = "Database Tables:\n\n"

            for (table_name,) in tables:
                # Get row count for each table - use parameterized identifier
                # SQLite doesn't support parameterized table names, so we validate the name
                # Table names from sqlite_master are safe, but we sanitize anyway
                safe_table_name = "".join(c for c in table_name if c.isalnum() or c == "_")
                if safe_table_name != table_name:
                    output += f"  - {table_name} (skipped - unsafe name)\n"
                    continue
                try:
                    cursor.execute(f'SELECT COUNT(*) FROM "{safe_table_name}"')
                    count = cursor.fetchone()[0]
                    output += f"  - {table_name} ({count} rows)\n"
                except sqlite3.Error:
                    output += f"  - {table_name} (count unavailable)\n"

            output += f"\nTotal: {len(tables)} table(s)"
            return output

    except ValueError as e:
        return f"Error: {str(e)}"
    except sqlite3.OperationalError as e:
        return (
            f"SQLite operational error: {str(e)}\nHint: Database may be locked. Close other connections and try again."
        )
    except sqlite3.Error as e:
        return f"SQLite error: {str(e)}"
    except Exception as e:
        logger.exception(f"Error listing tables: {e}")
        return f"Error listing tables: {str(e)}"


def _start_server(port: int) -> str:
    """Start the Next.js development server for the current project."""
    get_tool_env()
    global server_process, server_port

    # Validate port
    try:
        validate_port(port)
    except ValueError as e:
        return f"Error: {str(e)}"

    try:
        project_path = get_current_project()

        # Check if server is already running
        if server_process and server_process.poll() is None:
            return (
                f"Error: Server already running on port {server_port}.\n"
                f"Hint: Stop it first with stop_dev_server() or use restart_dev_server({port})"
            )

        # Check if node_modules exists
        node_modules = project_path / "node_modules"
        if not node_modules.exists():
            return "Error: node_modules not found.\nHint: Run install_dependencies() first, then try again."

        # Check if package.json exists
        package_json = project_path / "package.json"
        if not package_json.exists():
            return (
                "Error: package.json not found.\n"
                "This doesn't appear to be a Node.js project.\n"
                "Hint: Make sure you've selected the correct project with set_current_project()"
            )

        # Set PORT environment variable and start dev server
        env = os.environ.copy()
        env["PORT"] = str(port)

        # Start the server in a new process group so we can kill all child processes
        popen_kwargs = {
            "cwd": str(project_path),
            "env": env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }

        if platform.system() != "Windows":
            popen_kwargs["start_new_session"] = True
        else:
            # On Windows, use CREATE_NEW_PROCESS_GROUP flag
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        logger.info(f"Starting development server on port {port} for project {project_path.name}")
        server_process = subprocess.Popen(["npm", "run", "dev"], **popen_kwargs)

        server_port = port

        return (
            f"Development server starting on port {port}\n"
            f"URL: http://localhost:{port}\n"
            f"Project: {project_path.name}\n"
            f"Process ID: {server_process.pid}\n\n"
            f"Note: Server is running in background. Use stop_dev_server() to stop it.\n"
            f"Use server_status() to check if the server is running."
        )

    except ValueError as e:
        return f"Error: {str(e)}"
    except FileNotFoundError:
        return "Error: npm not found.\nHint: Install Node.js and npm first. Visit https://nodejs.org/"
    except Exception as e:
        logger.exception(f"Error starting server: {e}")
        return f"Error starting server: {str(e)}"


def _stop_server() -> str:
    """Stop the currently running development server."""
    global server_process, server_port

    try:
        if server_process is None:
            return "No server process is being tracked.\nHint: Start a server first with start_dev_server()"

        if server_process.poll() is not None:
            exit_code = server_process.returncode
            server_process = None
            old_port = server_port
            server_port = None
            return (
                f"Server was not running (already exited with code {exit_code}).\n"
                f"Previous port: {old_port}\n"
                "Hint: Use start_dev_server() to start a new server."
            )

        # Get the port before stopping
        port = server_port

        # Terminate the process and all its children
        logger.info(f"Stopping development server on port {port}")

        try:
            if platform.system() != "Windows":
                # On Unix, kill the entire process group
                os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
            else:
                # On Windows, terminate the process
                server_process.terminate()
        except (ProcessLookupError, OSError):
            pass  # Process already terminated

        try:
            # Wait for graceful shutdown
            server_process.wait(timeout=DEFAULT_SHUTDOWN_TIMEOUT)
            logger.info("Server stopped gracefully")
        except subprocess.TimeoutExpired:
            # Force kill if it doesn't stop gracefully
            logger.warning("Graceful shutdown timed out, forcing kill")
            try:
                if platform.system() != "Windows":
                    os.killpg(os.getpgid(server_process.pid), signal.SIGKILL)
                else:
                    server_process.kill()
            except (ProcessLookupError, OSError):
                pass  # Process already terminated
            server_process.wait()

        server_process = None
        server_port = None

        return f"Development server stopped (was running on port {port})"

    except Exception as e:
        logger.exception(f"Error stopping server: {e}")
        return f"Error stopping server: {str(e)}"


def _restart_server(port: Optional[int]) -> str:
    """Restart the development server (stop and start again)."""
    get_tool_env()
    global server_port

    # Validate port if specified
    if port is not None:
        try:
            validate_port(port)
        except ValueError as e:
            return f"Error: {str(e)}"

    # Use current port if not specified
    if port is None:
        if server_port is None:
            return (
                "Error: No server was running and no port specified.\n"
                "Hint: Use start_dev_server(port) to start a server, or specify a port."
            )
        port = server_port

    # Stop the server
    stop_result = _stop_server()

    # Wait a moment for port to be released
    time.sleep(1)

    # Start the server
    start_result = _start_server(port=port)

    return f"Server restarted:\n\n{stop_result}\n\n{start_result}"


def _server_status() -> str:
    """Check the status of the development server."""
    get_tool_env()
    global server_process, server_port

    if server_process is None:
        return "No server process tracked.\nHint: Start a server with start_dev_server()"

    if server_process.poll() is not None:
        exit_code = server_process.returncode
        return (
            f"Server process has stopped (exit code: {exit_code}).\n"
            f"Previous port: {server_port}\n"
            "Hint: Check server logs or restart with start_dev_server()"
        )

    return (
        f"Server is running\n"
        f"URL: http://localhost:{server_port}\n"
        f"Process ID: {server_process.pid}\n"
        f"Project: {current_project_path.name if current_project_path else 'Unknown'}"
    )


def _install_deps() -> str:
    """Install npm dependencies for the current project."""
    get_tool_env()

    try:
        project_path = get_current_project()

        # Check if package.json exists
        package_json = project_path / "package.json"
        if not package_json.exists():
            return (
                "Error: package.json not found.\n"
                "This doesn't appear to be a Node.js project.\n"
                "Hint: Make sure you've selected the correct project."
            )

        logger.info(f"Installing npm dependencies for {project_path.name}")

        # Run npm install with timeout
        try:
            result = subprocess.run(
                ["npm", "install"], cwd=str(project_path), capture_output=True, text=True, timeout=DEFAULT_NPM_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            return (
                f"Error: npm install timed out after {DEFAULT_NPM_TIMEOUT} seconds.\n"
                "Hint: Check your network connection or try running 'npm install' manually.\n"
                "Large projects may need more time."
            )

        if result.returncode == 0:
            logger.info("Dependencies installed successfully")
            return (
                f"Dependencies installed successfully\n"
                f"node_modules created in {project_path}\n"
                f"\nNext step: Run start_dev_server() to start the development server."
            )
        else:
            # Extract useful error info
            stderr = result.stderr.strip()
            if "ERESOLVE" in stderr:
                return (
                    f"Error: Dependency resolution conflict.\n"
                    f"Details: {stderr[:500]}...\n"
                    f"Hint: Try 'npm install --legacy-peer-deps' manually."
                )
            elif "ENOENT" in stderr:
                return (
                    f"Error: Missing file or directory.\n"
                    f"Details: {stderr[:500]}...\n"
                    f"Hint: Check that all required files exist in the project."
                )
            return (
                f"Error installing dependencies:\n"
                f"{stderr[:1000]}\n"
                f"Hint: Check the error message above and try running 'npm install' manually for more details."
            )

    except ValueError as e:
        return f"Error: {str(e)}"
    except FileNotFoundError:
        return "Error: npm not found.\nHint: Install Node.js and npm first. Visit https://nodejs.org/"
    except Exception as e:
        logger.exception(f"Error installing dependencies: {e}")
        return f"Error installing dependencies: {str(e)}"


# ============================================================================
# Web Tools (split by function)
# ============================================================================


@tool(name="web_init")
async def web_init_tool(
    name: Annotated[str, "Name of the web project to be created (used as directory name)."],
    title: Annotated[str, "Title of the web project (used as project title)."],
    description: Annotated[str, "Description of the web project."],
    scaffold: Annotated[Literal["web-static", "web-db-user"], "Project scaffold type."],
) -> str:
    """Initialize a new web app project with scaffold, automated environment setup and hosting services.

    <instructions>
    - Always init project first before making detailed plans; there's a lot of information that can be learned after the project is initialized.
    - Creates scaffolding under the workspace with automated environment setup.
    - `web-db-user` provides: user auth, database, backend API, external API integrations (LLM, S3, Voice, Image Generation).
    - `web-static` cannot securely handle API keys or server-side operations.
    - The website you create cannot access any user's MCP tools.
    - DO NOT use parallel processing in web development projects.
    </instructions>

    <recommended_usage>
    - Use "web-static" for portfolios, landing pages, or single-user utilities.
    - Use "web-db-user" for task managers, collaborative tools, or apps needing auth/database/external APIs.
    </recommended_usage>
    """
    try:
        return _init_project(name, title, description, scaffold)
    except Exception as e:
        logger.exception("web_init_tool error: %s", e)
        return error_result(f"Web init failed: {e}", hint="An unexpected error occurred during project initialization.")


_WEB_PROJECT_ALIASES: dict[str, str] = {
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


@tool(name="web_project")
async def web_project_tool(
    action: Annotated[
        Literal["set", "list"], "The action to perform: 'set' to switch active project, 'list' to show all projects."
    ],
    name: Annotated[str | None, "Project name. Required for 'set' action."] = None,
) -> str:
    """Manage web projects in the workspace — switch between or list projects.

    <instructions>
    - Use 'set' to switch the active project context.
    - Use 'list' to see all available projects in the workspace.
    </instructions>
    """
    action, _alias = resolve_alias(action, _WEB_PROJECT_ALIASES)

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
        logger.exception("web_project_tool error: %s", e)
        return error_result(f"Web project operation failed: {e}", hint="An unexpected error occurred.")


_WEB_SERVER_ALIASES: dict[str, str] = {
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


@tool(name="web_server")
async def web_server_tool(
    action: Annotated[Literal["start", "stop", "restart", "status", "install_deps"], "Server action to perform."],
    port: Annotated[int | None, "Server port. Optional for start and restart. Defaults to 3000."] = None,
) -> str:
    """Manage the Next.js development server lifecycle and dependencies.

    <instructions>
    - Use 'start' to launch the development server for preview.
    - Use 'install_deps' to install or update project dependencies.
    - Use 'status' to check if the server is running.
    - Use 'stop' to shut down the running server.
    - Use 'restart' to stop and start the server, optionally on a new port.
    </instructions>
    """
    action, _alias = resolve_alias(action, _WEB_SERVER_ALIASES)

    try:
        if action == "start":
            return alias_hint(_start_server(port if port is not None else 3000), _alias, action)
        elif action == "stop":
            return alias_hint(_stop_server(), _alias, action)
        elif action == "restart":
            return alias_hint(_restart_server(port), _alias, action)
        elif action == "status":
            return alias_hint(_server_status(), _alias, action)
        elif action == "install_deps":
            return alias_hint(_install_deps(), _alias, action)
        else:
            return error_result(
                f"Unknown action '{action}'.", hint="Valid actions: start, stop, restart, status, install_deps."
            )
    except Exception as e:
        logger.exception("web_server_tool error: %s", e)
        return error_result(f"Web server operation failed: {e}", hint="An unexpected error occurred.")


_WEB_ENV_ALIASES: dict[str, str] = {
    "set": "add",
    "create": "add",
    "define": "add",
    "put": "add",
    "insert": "add",
    "update": "add",
    "delete": "remove",
    "unset": "remove",
    "drop": "remove",
    "clear": "remove",
    "erase": "remove",
    "show": "list",
    "display": "list",
    "ls": "list",
    "get": "list",
    "view": "list",
    "read": "list",
}


@tool(name="web_env")
async def web_env_tool(
    action: Annotated[Literal["add", "remove", "list"], "Environment variable action."],
    key: Annotated[str | None, "Environment variable key. Required for 'add' and 'remove'."] = None,
    value: Annotated[str | None, "Environment variable value. Required for 'add'."] = None,
    env_file: Annotated[str, "Target env file name. Defaults to .env.local."] = ".env.local",
) -> str:
    """Manage environment variables for the current web project.

    <instructions>
    - Use 'add' to set or update an environment variable.
    - Use 'remove' to delete an environment variable.
    - Use 'list' to view all variables in an env file (values are partially hidden).
    </instructions>
    """
    action, _alias = resolve_alias(action, _WEB_ENV_ALIASES)

    try:
        if action == "add":
            if not key:
                return error_result(
                    "'key' is required for 'add' action.",
                    hint="Use action='add' with key='VAR_NAME' and value='var_value'.",
                )
            if value is None:
                return error_result(
                    "'value' is required for 'add' action.",
                    hint="Use action='add' with key='VAR_NAME' and value='var_value'.",
                )
            return alias_hint(_add_env(key, value, env_file), _alias, action)
        elif action == "remove":
            if not key:
                return error_result(
                    "'key' is required for 'remove' action.", hint="Use action='remove' with key='VAR_NAME'."
                )
            return alias_hint(_remove_env(key, env_file), _alias, action)
        elif action == "list":
            return alias_hint(_list_env(env_file), _alias, action)
        else:
            return error_result(f"Unknown action '{action}'.", hint="Valid actions: add, remove, list.")
    except Exception as e:
        logger.exception("web_env_tool error: %s", e)
        return error_result(f"Web env operation failed: {e}", hint="An unexpected error occurred.")


_WEB_DB_ALIASES: dict[str, str] = {
    "sql": "query",
    "select": "query",
    "execute": "query",
    "run": "query",
    "fetch": "query",
    "tables": "list_tables",
    "schema": "list_tables",
    "show_tables": "list_tables",
    "structure": "list_tables",
    "describe": "list_tables",
}


@tool(name="web_db")
async def web_db_tool(
    action: Annotated[Literal["query", "list_tables"], "Database action."],
    query: Annotated[str | None, "SQL query to execute. Required for 'query' action."] = None,
    fetch: Annotated[bool, "Whether to fetch results for SQL queries. Defaults to true."] = True,
) -> str:
    """Interact with the current web project's SQLite database.

    <instructions>
    - Use 'query' to execute SQL statements against the project database.
    - Use 'list_tables' to see all tables and their row counts.
    </instructions>
    """
    action, _alias = resolve_alias(action, _WEB_DB_ALIASES)

    try:
        if action == "query":
            if not query:
                return error_result(
                    "'query' is required for 'query' action.",
                    hint="Use action='query' with query='SELECT * FROM table'.",
                )
            return alias_hint(_execute_sql(query, fetch), _alias, action)
        elif action == "list_tables":
            return alias_hint(_list_tables(), _alias, action)
        else:
            return error_result(f"Unknown action '{action}'.", hint="Valid actions: query, list_tables.")
    except Exception as e:
        logger.exception("web_db_tool error: %s", e)
        return error_result(f"Web DB operation failed: {e}", hint="An unexpected error occurred.")


WEB_TOOLS = [web_init_tool, web_project_tool, web_server_tool, web_env_tool, web_db_tool]
