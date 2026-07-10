FROM registry.redhat.io/ubi9/python-311:9.7

LABEL name="mcp-slack" \
      description="Slack MCP server — channel/message/thread access" \
      maintainer="afarley@redhat.com"

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade setuptools pip && \
    pip install --no-cache-dir -r requirements.txt

COPY slack_mcp_server.py ./

RUN useradd -u 1001 -r -s /sbin/nologin mcp
USER 1001

CMD ["python", "slack_mcp_server.py"]
