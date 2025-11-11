FROM registry.redhat.io/ubi9/python-311:9.7

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY slack_mcp_server.py ./

CMD ["python", "slack_mcp_server.py"]
