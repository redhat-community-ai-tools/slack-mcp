FROM registry.access.redhat.com/ubi9/python-311:9.7

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade setuptools pip && \
    pip install --no-cache-dir -r requirements.txt

COPY slack_mcp_server.py formatting_guide.json ./
COPY scripts/update_formatting_guide.py ./scripts/

# Validate the formatting guide against Slack's live docs (best-effort).
# In hermetic builds without network, this logs a warning and continues.
RUN python scripts/update_formatting_guide.py --check || true

CMD ["python", "slack_mcp_server.py"]
