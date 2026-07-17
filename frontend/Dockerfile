# 前端生产镜像：node 构建静态产物 → nginx 提供静态 + 反代 /api 到后端
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
USER root
RUN apk upgrade --no-cache
USER 101
ENV BACKEND_HOST=backend \
    BACKEND_PORT=8000
COPY docker/nginx/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
