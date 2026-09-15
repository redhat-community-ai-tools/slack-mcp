FROM registry.access.redhat.com/ubi9/python-311:9.8-1779945715

WORKDIR /app

# Install the package (deps + the slack-mcp entry point) from pyproject.toml
COPY pyproject.toml README.md ./
COPY slack_mcp_server.py ./
RUN pip install --no-cache-dir --upgrade setuptools pip && \
    pip install --no-cache-dir .

# User cache lives here; mount a volume to persist it across restarts
ENV SLACK_MCP_DATA=/app/data

CMD ["slack-mcp"]
