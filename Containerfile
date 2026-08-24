FROM registry.access.redhat.com/ubi9/python-311:9.7

WORKDIR /app

# Install the package (deps + the slack-mcp entry point) from pyproject.toml
COPY pyproject.toml README.md ./
COPY slack_mcp_server.py ./
RUN pip install --no-cache-dir --upgrade setuptools pip && \
    pip install --no-cache-dir .

# User cache lives here; mount a volume to persist it across restarts.
# chgrp/chmod so UID 1001 (and any arbitrary UID in group 0 on OpenShift)
# can write cache files without a volume mount.
ENV SLACK_MCP_DATA=/app/data
USER 0
RUN mkdir -p /app/data && chgrp -R 0 /app/data && chmod -R g=u /app/data
USER 1001

CMD ["slack-mcp"]
