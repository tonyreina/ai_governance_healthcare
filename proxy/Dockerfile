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

FROM caddy:2@sha256:8dc9fa87b36b25303d1c67d2a09f5824b7f3bfd72cb052f246e5da2133fe29a8

COPY proxy/Caddyfile /etc/caddy/Caddyfile

# The Content-Security-Policy, generated from the built dashboard by
# scripts/build_app.py: its script-src is the hash of that page's script (#154).
COPY proxy/csp.caddy /etc/caddy/csp.caddy

# The single self-contained index.html produced by scripts/build_app.py.
COPY docs/app/ /srv/app/

# Unprivileged, like the compose stack's proxy (#50). /data and /config are where
# Caddy keeps certificates and config, so they are handed to this user here; in
# the image there is no root-owned volume to fix afterwards. The listener is on
# 8080, which needs no privilege.
RUN chown -R 65532:65532 /data /config
USER 65532:65532

# Cloud Run hands the port in $PORT (8080 by default) and routes only to the
# ingress container; sidecars are reachable on localhost and nowhere else.
# ECS awsvpc and Container Apps give the same localhost-only arrangement.
ENV SITE_ADDRESS=http://:8080
EXPOSE 8080

# Fail the build rather than ship a proxy that will not start.
RUN caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
