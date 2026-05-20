FROM registry.redhat.io/ubi9/python-311:9.8-1777569679

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade setuptools pip && \
    pip install --no-cache-dir -r requirements.txt

COPY slack_mcp_server.py ./

CMD ["python", "slack_mcp_server.py"]
