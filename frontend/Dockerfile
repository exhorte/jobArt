# jobArt - image frontend (Next.js, sortie « standalone »).
# Contexte de build : ./frontend.   docker compose build frontend
# BACKEND_URL est lue à l'EXÉCUTION par le proxy /api (aucune URL n'est figée dans l'image).
FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    BACKEND_URL=http://backend:8000
RUN addgroup -S -g 10001 jobart && adduser -S -u 10001 -G jobart jobart
COPY --from=build --chown=jobart:jobart /app/.next/standalone ./
COPY --from=build --chown=jobart:jobart /app/.next/static ./.next/static
COPY --from=build --chown=jobart:jobart /app/public ./public
USER jobart
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1
CMD ["node", "server.js"]
