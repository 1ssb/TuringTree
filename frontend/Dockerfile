# syntax=docker/dockerfile:1
#
# RagIndex frontend — built with Vite, then served as static files by nginx,
# which also reverse-proxies "/api/..." to the backend service.
#
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . ./
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
