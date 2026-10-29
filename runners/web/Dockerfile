FROM mcr.microsoft.com/playwright:v1.64.1-noble

WORKDIR /runner
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force \
    && mkdir -p /runner/artifacts && chown -R pwuser:pwuser /runner/artifacts
COPY src ./src

USER pwuser
ENV NODE_ENV=production
CMD ["node", "src/worker.js"]
