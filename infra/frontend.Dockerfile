# Integration point for TASK-006.
FROM node:24-bookworm-slim
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
RUN chown node:node /app
USER node
COPY --chown=node:node frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY --chown=node:node frontend/ ./
# Next.js evaluates rewrites during the production build.
ENV API_INTERNAL_ORIGIN=http://api:8000
RUN npm run build
ENV NODE_ENV=production
CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
