FROM mcr.microsoft.com/playwright:v1.64.1-noble

WORKDIR /runner
COPY web/package.json web/package-lock.json ./
# @playwright/mcp@0.0.83 is pinned, but npm overrides force playwright-core
# 1.64.1 so the server uses Chromium revision 1248 already in this image.
# Do not launch with npx or --browser=chrome; those pull a different browser.
RUN npm ci --omit=dev --ignore-scripts \
    && node --input-type=module -e "import {createRequire} from 'node:module'; import {readFileSync} from 'node:fs'; import {dirname, join} from 'node:path'; const require=createRequire('/runner/package.json'); const mcp=require('@playwright/mcp/package.json'); const corePath=require.resolve('playwright-core/package.json'); const core=require(corePath); const revision=JSON.parse(readFileSync(join(dirname(corePath), 'browsers.json'))).browsers.find((item)=>item.name==='chromium').revision; if (mcp.version!=='0.0.83' || core.version!=='1.64.1' || revision!=='1248') throw new Error(mcp.version+' '+core.version+' rev '+revision);" \
    && npm cache clean --force \
    && mkdir -p /runner/artifacts && chown -R pwuser:pwuser /runner/artifacts
COPY web/src ./web/src
COPY common ./common

USER pwuser
ENV NODE_ENV=production
CMD ["node", "web/src/worker.js"]
