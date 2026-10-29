FROM node:22-alpine
WORKDIR /runner
COPY runners/common ./common
COPY runners/api/src ./api/src
USER node
ENV NODE_ENV=production
CMD ["node", "api/src/worker.js"]
