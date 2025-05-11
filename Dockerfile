FROM ghcr.io/osgeo/gdal:ubuntu-small-3.11.0 AS builder

# Install security updates and system dependencies, then clean up
RUN export DEBIAN_FRONTEND=noninteractive && \
    apt-get update && \
    apt-get --yes upgrade && \
    # these are our own dependencies and utilities
    # if you need to add more, please sort them in alphabetical order
    apt-get install --yes --no-install-recommends \
        tini \
        git && \
    apt-get --yes clean && \
    rm -rf /var/lib/apt/lists/*

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory for dependency installation
WORKDIR /app

# Copy dependency files
COPY pyproject.toml .env pygeoapi-config.yml ./

# Install dependencies as root (with system-wide access)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --break-system-packages -r pyproject.toml

# Create a normal non-root user to run the app
RUN useradd --create-home appuser
RUN mkdir -p /home/appuser/app /home/appuser/data && \
    chown -R appuser:appuser /home/appuser

# Copy the app to the user directory
COPY --chown=appuser:appuser . /home/appuser/app/

# Set working directory to user app directory
WORKDIR /home/appuser/app

# Switch to non-root user for remaining operations
USER appuser

ENV PATH="$PATH:/home/appuser/.local/bin" \
    PYTHONFAULTHANDLER=1 \
    PYTHONUNBUFFERED=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_BREAK_SYSTEM_PACKAGES=1

# Write git commit identifier into the image
ARG GIT_COMMIT
ENV GIT_COMMIT=$GIT_COMMIT
RUN echo $GIT_COMMIT > /home/appuser/git-commit.txt

# Compile python bytecode for faster startup times
RUN python -c "import compileall; compileall.compile_path(maxlevels=10)"

# Use tini as the init process
ENTRYPOINT ["tini", "-g", "--"]

# Run using fastapi CLI directly
CMD ["fastapi", "run", "app/main.py", "--app", "app", "--host", "0.0.0.0", "--port", "5000"]
