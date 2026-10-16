# Analyst UI (Workstream C's code, packaging by Workstream B): build with Vite, serve the
# static files with nginx. The public nginx in front proxies / here and /api to the API.
FROM node:22-alpine AS build
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY deploy/nginx/ui-static.conf /etc/nginx/conf.d/default.conf
COPY --from=build /ui/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=6 CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
