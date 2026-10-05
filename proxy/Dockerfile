# Bake the proxy for a cloud deployment.
#
# compose.yaml does NOT use this file: locally the Caddyfile and the dashboard
# are bind-mounted, so editing either takes effect on `docker compose restart
# proxy` with no rebuild. But Cloud Run, ECS and Container Apps have nothing to
# bind-mount from -- the config and the static file have to be inside an image.
#
# The dashboard is COPIED, not built. Build it on the host first:
#
#     pixi run build-app
#     docker build -f proxy/Dockerfile -t REGISTRY/chai-proxy:$(git rev-parse --short HEAD) .
#
# Build context is the repository root, because docs/app/ is outside proxy/.

FROM caddy:2

COPY proxy/Caddyfile /etc/caddy/Caddyfile

# The single self-contained index.html produced by scripts/build_app.py.
COPY docs/app/ /srv/app/

# Cloud Run hands the port in $PORT (8080 by default) and routes only to the
# ingress container; sidecars are reachable on localhost and nowhere else.
# ECS awsvpc and Container Apps give the same localhost-only arrangement.
ENV SITE_ADDRESS=http://:8080
EXPOSE 8080

# Fail the build rather than ship a proxy that will not start.
RUN caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
