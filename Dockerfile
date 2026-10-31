FROM python:3.12-slim

WORKDIR /app
COPY requirements-auditor.txt .
RUN pip install --no-cache-dir -r requirements-auditor.txt \
    && solc-select install 0.8.20 \
    && solc-select use 0.8.20

COPY auditor.py bytecode.py chain.py etherscan.py server.py warden_scan.py ./
COPY schema ./schema

# ETHERSCAN_API_KEY is set as a host environment variable, never baked into the image.
ENV PORT=8000
EXPOSE 8000
CMD ["python", "server.py"]
