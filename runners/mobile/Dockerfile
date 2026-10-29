FROM node:22-alpine
WORKDIR /runner
COPY runners/common ./common
COPY runners/mobile/src ./mobile/src
USER node
ENV NODE_ENV=production
CMD ["node", "mobile/src/worker.js"]
