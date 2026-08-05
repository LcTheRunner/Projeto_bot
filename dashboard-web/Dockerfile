# syntax=docker/dockerfile:1.7
FROM node:24-alpine AS build
WORKDIR /workspace
COPY package*.json ./
COPY . .
RUN --mount=type=cache,target=/root/.npm \
    npm ci && npm run build && rm -rf node_modules

FROM nginx:1.29-alpine-slim
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/dist/dashboard-web/browser /usr/share/nginx/html
EXPOSE 80
