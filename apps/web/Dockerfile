# syntax=docker/dockerfile:1.7

# The mini app is static once built. nginx serves it; the API is a different
# container behind the same origin, so there is no proxying to do here.

FROM node:24-alpine AS builder

WORKDIR /app

RUN corepack enable

# Dependencies first, from the lockfile, so editing a component does not
# reinstall node_modules.
# pnpm-workspace.yaml too: pnpm 11 keeps overrides there, and installing with
# a frozen lockfile that records overrides the config does not declare is a
# hard error.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile

COPY . .

# mkcert wants a system trust store to write into; a build does not need HTTPS.
ENV VITE_NO_HTTPS=1
RUN pnpm build


# The unprivileged variant rather than plain nginx: it already listens on 8080,
# already runs as a non-root user, and already puts the pid and every temp path
# somewhere that user can write. Patching the stock image to do the same means
# fighting its own nginx.conf over the pid directive.
FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080
