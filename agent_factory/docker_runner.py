"""Docker image build and container lifecycle.

The image is built from agent_factory/templates/Dockerfile. It's a
generic Ubuntu + Node + Claude Code base. The user can override which
image is used per run via --image; the harness will not rebuild a
user-supplied image.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from importlib import resources
from pathlib import Path

from agent_factory.config import ProjectLayout

log = logging.getLogger(__name__)

TEMPLATES_PACKAGE = "agent_factory.templates"
DEFAULT_MODEL = "claude-opus-4-6"


class DockerError(RuntimeError):
    pass


def _docker_available() -> None:
    if shutil.which("docker") is None:
        raise DockerError("docker CLI not found. Install Docker Desktop.")
    result = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if result.returncode != 0:
        raise DockerError("Docker daemon not running. Start Docker Desktop.")


def _materialise_template_dir() -> Path:
    """Copy bundled templates onto disk so `docker build` can see them."""
    tmp = Path(tempfile.mkdtemp(prefix="agent-factory-build-"))
    files = resources.files(TEMPLATES_PACKAGE)
    # Only the in-container entrypoint is baked into the image. judge.sh
    # ships into the user's repo (via repo.py), so users can edit it without
    # rebuilding the image.
    for entry in ("Dockerfile", "entrypoint.sh"):
        src_text = files.joinpath(entry).read_text()
        target = tmp / entry
        target.write_text(src_text)
        if entry.endswith(".sh"):
            target.chmod(0o755)
    return tmp


def build_image(layout: ProjectLayout) -> str:
    """Build the agent image for this project. Returns image tag."""
    _docker_available()
    build_ctx = _materialise_template_dir()
    try:
        log.info("Building image %s ...", layout.image_tag)
        result = subprocess.run(
            ["docker", "build", "-t", layout.image_tag, str(build_ctx)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise DockerError(f"docker build failed:\n{result.stdout}\n{result.stderr}")
        log.info("Image built: %s", layout.image_tag)
        return layout.image_tag
    finally:
        shutil.rmtree(build_ctx, ignore_errors=True)


def _run_docker(args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run a docker subcommand. Returns None if the docker binary is missing."""
    try:
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None


def list_running(layout: ProjectLayout) -> list[str]:
    """Return names of containers matching this project's prefix."""
    result = _run_docker(["ps", "--filter", f"name={layout.run_prefix}", "--format", "{{.Names}}"])
    if result is None or result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def remove_existing(layout: ProjectLayout) -> None:
    """Force-remove any leftover containers from a previous run."""
    for i in range(1, 65):
        name = f"{layout.run_prefix}-{i}"
        _run_docker(["rm", "-f", name])


def launch_agents(
    layout: ProjectLayout,
    num_agents: int,
    claude_config_dir: Path,
    model: str = DEFAULT_MODEL,
    memory: str = "8g",
    cpus: float = 2,
) -> list[str]:
    """Spawn N detached agent containers. Returns container names.

    The in-container `claude` authenticates by reading the host's claude
    credentials, bind-mounted read-only at /home/agent/.claude. No API
    key is needed; the host login (Max subscription / OAuth / API key
    in claude config) is inherited.
    """
    _docker_available()
    if not claude_config_dir.is_dir():
        raise DockerError(
            f"Host claude config directory not found at {claude_config_dir}. "
            "Run `claude` once on the host to log in first."
        )
    layout.log_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for i in range(1, num_agents + 1):
        name = f"{layout.run_prefix}-{i}"
        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--restart",
            "unless-stopped",
            "-v",
            f"{layout.upstream_repo}:/upstream:rw",
            "-v",
            f"{layout.log_dir}:/workspace/agent_logs:rw",
            "-v",
            f"{claude_config_dir}:/home/agent/.claude:ro",
            "-e",
            f"AGENT_ID={name}",
            "-e",
            f"AGENT_MODEL={model}",
            "--memory",
            memory,
            "--cpus",
            str(cpus),
            layout.image_tag,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise DockerError(f"Failed to start {name}:\n{result.stdout}\n{result.stderr}")
        log.info("Started %s", name)
        names.append(name)
    return names


def stop_agents(layout: ProjectLayout, grace_seconds: int = 30) -> None:
    """Send SIGTERM (graceful) to all matching containers. The in-container
    trap saves uncommitted work before exiting."""
    names = list_running(layout)
    if not names:
        return
    log.info("Stopping %d agents (grace %ds for SIGTERM save)...", len(names), grace_seconds)
    subprocess.run(
        ["docker", "stop", "-t", str(grace_seconds), *names],
        capture_output=True,
        text=True,
        check=False,
    )


def container_status(layout: ProjectLayout) -> list[dict[str, str]]:
    """Rows of {name, uptime} for running agents."""
    result = _run_docker(
        ["ps", "--filter", f"name={layout.run_prefix}", "--format", "{{.Names}}\t{{.RunningFor}}"]
    )
    rows: list[dict[str, str]] = []
    if result is None:
        return rows
    for line in result.stdout.splitlines():
        if "\t" in line:
            name, uptime = line.split("\t", 1)
            rows.append({"name": name, "uptime": uptime})
    return rows


def exec_in_container(container: str, *cmd: str) -> str:
    """Run a command inside a running container; return stdout (best effort)."""
    result = _run_docker(["exec", container, *cmd])
    if result is None:
        return ""
    return result.stdout
