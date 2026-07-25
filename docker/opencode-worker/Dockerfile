ARG NODE_IMAGE=node:24.4.1-bookworm-slim
FROM ${NODE_IMAGE}

ARG OPENCODE_VERSION
RUN test -n "${OPENCODE_VERSION}" \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates git openssh-client tini \
    && npm install --global "opencode-ai@${OPENCODE_VERSION}" \
    && npm cache clean --force \
    && rm -rf /var/lib/apt/lists/*
RUN opencode --version | grep -F "${OPENCODE_VERSION}" \
    && opencode run --help 2>&1 | grep -F -- "--dangerously-skip-permissions" \
    && opencode run --help 2>&1 | grep -F -- "--format"

COPY --chown=node:node opencode.json /opt/opencode/opencode.json
COPY --chmod=0755 entrypoint.sh /usr/local/bin/worker-entrypoint

USER node
WORKDIR /workspace
ENV OPENCODE_CONFIG=/opt/opencode/opencode.json \
    OPENCODE_DISABLE_AUTOUPDATE=true \
    OPENCODE_AUTO_SHARE=false
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/worker-entrypoint"]
CMD ["help"]
