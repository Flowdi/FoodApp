FROM node:22-alpine AS build
WORKDIR /app
ARG APP_NAME=Vorrat
ENV APP_NAME=$APP_NAME
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build
FROM caddy:2.9-alpine
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
