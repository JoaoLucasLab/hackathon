# Frontend image: builds the Vite app and serves it with nginx, which also proxies
# the API paths to the backend container, so the browser sees ONE origin
# (no CORS, no cross-site cookie). Build context is the REPO ROOT, because the
# frontend tests (type-checked by `npm run build`) import ../fixtures/*.json:
#   docker build -f frontend/Dockerfile -t course-planner-web .
# Used by the WSL backup host. On Render the same `npm run build` output is a static site.

FROM node:22-alpine AS build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
# The .dockerignore lets in only the fixture JSON the tests import.
COPY fixtures/ /src/fixtures/
COPY frontend/ ./
# VITE_* values are baked into the bundle at build time. Never put a secret here.
# Empty VITE_API_BASE_URL = same origin (nginx proxies /api to the backend).
ARG VITE_API_BASE_URL=
ARG VITE_FEATURE_AUDIT_UPLOAD=false
ARG VITE_FEATURE_CONVERSATIONAL_PLANNER=false
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_FEATURE_AUDIT_UPLOAD=$VITE_FEATURE_AUDIT_UPLOAD \
    VITE_FEATURE_CONVERSATIONAL_PLANNER=$VITE_FEATURE_CONVERSATIONAL_PLANNER
RUN npm run build

FROM nginx:1.27-alpine
# BACKEND_URL is substituted into the template by the nginx image at start-up.
ENV BACKEND_URL=http://backend:8000
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /src/frontend/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
