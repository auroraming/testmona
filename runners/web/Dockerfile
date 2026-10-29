FROM mcr.microsoft.com/playwright:v1.64.1-noble

WORKDIR /runner
COPY web/package.json web/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force \
    && mkdir -p /runner/artifacts && chown -R pwuser:pwuser /runner/artifacts
COPY web/src ./web/src
COPY common ./common

USER pwuser
ENV NODE_ENV=production
CMD ["node", "web/src/worker.js"]
