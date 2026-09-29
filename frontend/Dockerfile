# AutoStack frontend container for Railway.
# Build context: frontend/.  VITE_API_BASE is baked in at build time.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE
ENV VITE_API_BASE=$VITE_API_BASE
RUN test -n "$VITE_API_BASE" || (echo "Set VITE_API_BASE to the backend's public URL" && exit 1)
RUN npm run build

FROM nginx:1.27-alpine
# The nginx image renders /etc/nginx/templates/*.template with env vars (PORT) at start.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV PORT=8080
EXPOSE 8080
