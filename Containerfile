# Containerfile for meshgopher
FROM python:3.11-slim

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

# Default envs (override at runtime)
ENV MESH_PORT=4403

# System deps (optional but good practice)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates netbase iputils-ping telnet tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY meshie.py gopherlib.py main.py ./

# Use a minimal init to handle signals cleanly
ENTRYPOINT ["/usr/bin/tini", "--"]

# Run the app
CMD ["python", "main.py"]
