FROM registry.access.redhat.com/ubi9/python-312:latest

# --------------------------------------------------------------------------------------------------
# set the working directory to /app
# --------------------------------------------------------------------------------------------------

WORKDIR /app

# --------------------------------------------------------------------------------------------------
# Copy manifest files and install python packages
# --------------------------------------------------------------------------------------------------

USER root
COPY pyproject.toml /app/pyproject.toml
RUN pip install uv \
    && uv venv \
    && uv pip install -r pyproject.toml
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
USER default

# --------------------------------------------------------------------------------------------------
# copy source code and files
# --------------------------------------------------------------------------------------------------

COPY legal_mcp_server /app/legal_mcp_server

# --------------------------------------------------------------------------------------------------
# Copy the bundled statute corpus and reference data. Without this the image
# has no bare Acts and every statutory lookup reports itself as unavailable.
# Build it first on the host with:
#   python scripts/build_seed_acts.py && python scripts/fetch_corpus.py
# --------------------------------------------------------------------------------------------------

COPY data /app/data
ENV LEGAL_DATA_PATH=/app/data

# --------------------------------------------------------------------------------------------------
# Set PYTHONPATH to include /app
# --------------------------------------------------------------------------------------------------

ENV PYTHONPATH=/app

EXPOSE 5001

# --------------------------------------------------------------------------------------------------
# add entrypoint for the container
# --------------------------------------------------------------------------------------------------

CMD ["/app/.venv/bin/python", "-m", "legal_mcp_server.src.main"]
