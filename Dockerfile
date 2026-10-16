# The server: analyzer + MCP/web app. The pusher is NOT in here — it must run on a Mac (or the
# `macos` compose profile) because it reads the Messages database.
FROM astral/uv:0.9.30-python3.12-bookworm-slim
WORKDIR /app
COPY server/pyproject.toml server/uv.lock server/
RUN cd server && uv sync --frozen --no-dev --no-install-project
COPY analyzer analyzer
COPY server server
# personal.py and all data come from the /data volume, never the image
RUN rm -f analyzer/personal.py
ENV MONEY_DATA=/data PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["server/.venv/bin/python", "server/app.py"]
