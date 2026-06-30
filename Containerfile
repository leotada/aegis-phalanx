FROM fedora:latest

# Install base tools, compilers, dependencies, Node.js, and NPM
RUN dnf update -y && dnf install -y \
    curl git gh make gcc nodejs npm \
    python3 python3-pip python3-devel \
    postgresql-devel \
    && dnf clean all

ENV PATH="/root/.local/bin:/usr/local/bin:$PATH"

# Install only the agent CLI selected at build time (AGENT_TOOL in .env)
ARG AGENT_TOOL=agy
ENV AGENT_TOOL=${AGENT_TOOL}

COPY agents/tool_specs.py scripts/install_agent_tool.py /tmp/agent-install/
RUN AGENT_TOOL=${AGENT_TOOL} python3 /tmp/agent-install/install_agent_tool.py \
    && rm -rf /tmp/agent-install

# Install Telegram bot libraries and testing frameworks
RUN pip install --no-cache-dir \
    python-telegram-bot \
    pytest pytest-xdist psycopg2-binary

WORKDIR /workspace

# Copy orchestrator, agent package, and config files into the image
COPY telegram_listener.py .agyrules system_prompt.txt /workspace/
COPY agents/ /workspace/agents/
