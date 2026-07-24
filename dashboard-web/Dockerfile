FROM node:24-alpine AS build
WORKDIR /workspace
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.29-alpine
RUN apk add --no-cache apache2-utils
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint-dashboard.sh /usr/local/bin/docker-entrypoint-dashboard.sh
RUN chmod +x /usr/local/bin/docker-entrypoint-dashboard.sh
COPY --from=build /workspace/dist/dashboard-web/browser /usr/share/nginx/html
EXPOSE 80
ENTRYPOINT ["/usr/local/bin/docker-entrypoint-dashboard.sh"]
