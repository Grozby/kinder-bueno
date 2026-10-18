# Production UI: the Vue build served by nginx, which also proxies /api to the backend (deploy/default.conf.template).
FROM node:24-slim AS build
WORKDIR /frontend
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
# Baked into the bundle at build time; the defaults talk to the real backend and hide unfinished controls
ARG VITE_USE_MOCK=false
ARG VITE_SHOW_UNFINISHED=false
ENV VITE_USE_MOCK=$VITE_USE_MOCK VITE_SHOW_UNFINISHED=$VITE_SHOW_UNFINISHED
RUN npm run build

FROM nginx:1.27-alpine
# The image fills ${...} in templates from the environment at start: BACKEND_URL, API_TOKEN
COPY deploy/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /frontend/dist /usr/share/nginx/html
ENV BACKEND_URL=http://app:8000 API_TOKEN=""
EXPOSE 80
