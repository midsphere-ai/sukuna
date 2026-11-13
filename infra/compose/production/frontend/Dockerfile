FROM node:22-alpine AS builder

WORKDIR /app

COPY packages/frontend/package.json packages/frontend/package-lock.json ./
RUN npm ci

COPY packages/frontend/ ./
RUN npm run build

# Production stage
FROM node:22-alpine

WORKDIR /app

RUN addgroup -S sveltekit && adduser -S sveltekit -G sveltekit

COPY --from=builder --chown=sveltekit:sveltekit /app/build ./build
COPY --from=builder --chown=sveltekit:sveltekit /app/package.json ./
COPY --from=builder --chown=sveltekit:sveltekit /app/node_modules ./node_modules

USER sveltekit

ENV NODE_ENV=production
ENV PORT=3000

EXPOSE 3000

CMD ["node", "build"]
