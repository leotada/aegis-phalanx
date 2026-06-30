FROM fedora:latest

# Install base tools, compilers, dependencies, Node.js, and NPM
RUN dnf update -y && dnf install -y \
    curl git gh make gcc nodejs npm \
    python3 python3-pip python3-devel \
    postgresql-devel \
    && dnf clean all

# Install Claude Code CLI (Anthropic Official CLI)
RUN npm install -g @anthropic-ai/claude-code

# Install Antigravity CLI (Google Official CLI)
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash
ENV PATH="/root/.local/bin:/usr/local/bin:$PATH"

# Install Telegram bot libraries and testing frameworks
RUN pip install --no-cache-dir \
    python-telegram-bot \
    pytest pytest-xdist psycopg2-binary

WORKDIR /workspace
