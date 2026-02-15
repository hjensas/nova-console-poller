# Build stage
FROM docker.io/library/python:3.11.11-slim-bookworm AS builder

# Copy application files first
COPY requirements.txt /tmp/
COPY . /tmp/nova-console-poller/
WORKDIR /tmp/nova-console-poller

# Install build dependencies, create venv, install packages, then cleanup
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev git && \
    python -m venv /opt/venv && \
    . /opt/venv/bin/activate && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    pip install --no-cache-dir . && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/*

# Runtime stage
FROM docker.io/library/python:3.11.11-slim-bookworm

# Copy the virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set PATH to use the virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user and setup directories in one layer
RUN useradd -m -u 1000 -s /bin/bash poller && \
    mkdir -p /etc/openstack && \
    chown poller:poller /etc/openstack

# Switch to non-root user
USER poller

# Set the entrypoint to the installed command
ENTRYPOINT ["nova-console-poller"]
