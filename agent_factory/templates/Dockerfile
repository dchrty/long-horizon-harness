FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Minimal base: git, node (for Claude Code), python3 (used by judge.sh),
# plus the usual build tools so the agent can install whatever language
# toolchain its GOAL.md calls for.
RUN apt-get update && apt-get install -y \
    curl wget git build-essential pkg-config ca-certificates gnupg \
    python3 python3-pip jq bc sudo \
    && rm -rf /var/lib/apt/lists/*

# Node.js 20.x — Claude Code requires Node >= 18
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Non-root user — Claude Code refuses --dangerously-skip-permissions as root
RUN useradd -m -s /bin/bash agent \
    && echo "agent ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Git identity (agents push under this name).
# `safe.directory *` whitelists every mounted path so git doesn't refuse
# operations on /upstream when the host's UID doesn't match the container's
# `agent` user. This bites Windows hosts in particular: the bind-mount
# preserves a host UID that the container has no mapping for, and git's
# CVE-2022-24765 check fires with `fatal: detected dubious ownership in
# repository at '/upstream'`. The container is a single-tenant sandbox
# (only mounts are ones the harness controls), so global trust is safe.
RUN git config --system user.name "Claude Opus 4.6" \
    && git config --system user.email "noreply@anthropic.com" \
    && git config --system pull.rebase true \
    && git config --system rebase.autoStash true \
    && git config --system --add safe.directory '*'

# Workspace owned by agent
RUN mkdir -p /workspace && chown agent:agent /workspace

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER agent
WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
