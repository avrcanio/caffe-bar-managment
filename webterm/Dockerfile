FROM tsl0922/ttyd:latest

# Install Node.js 20 (for Codex CLI) + basic dev tools.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg git openssh-client; \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -; \
    apt-get install -y --no-install-recommends nodejs; \
    npm i -g @openai/codex; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*
