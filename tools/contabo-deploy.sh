#!/usr/bin/env bash
# contabo-deploy.sh — put calories.jp on the box without breaking what is on it.
#
# Dry-run by default, like the other fleet scripts: it inspects and prints, and
# changes nothing until --apply. Every apply step is preceded by the check that
# would have caught it going wrong, and the two failures already had on this
# project are checked explicitly:
#
#   * a volume mounted over /app/data hides the composition database that ships
#     inside the image, and every route returns 502;
#   * a container that cannot import its own modules replaces a working one,
#     because nothing asked it whether it had started.
#
#   ./tools/contabo-deploy.sh                    # dry-run, full preflight
#   sudo ./tools/contabo-deploy.sh --apply       # do it
#   ./tools/contabo-deploy.sh --verify           # read-only, after the fact
#
# Run from anywhere; paths are absolute.
set -Eeuo pipefail

APP_DIR=/opt/apps
SRC_DIR="${APP_DIR}/calories/src"
ENV_FILE="${APP_DIR}/calories/.env"
SERVICE=calories
PORT=8001
REPO=https://github.com/dwain-coder/calories.jp.git

DRY_RUN=1
VERIFY_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --apply)  DRY_RUN=0 ;;
    --verify) VERIFY_ONLY=1 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

fail=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; fail=1; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
would(){ [[ "${DRY_RUN}" -eq 1 ]] && printf '  would: %s\n' "$*" || { printf '  run:   %s\n' "$*"; eval "$*"; }; }

# ---------------------------------------------------------------- preflight
step "Preflight (read-only)"

[[ -d /opt/apps ]] && ok "/opt/apps exists" || bad "/opt/apps missing — is this the box?"

if command -v docker >/dev/null; then
  ok "docker $(docker --version | awk '{print $3}' | tr -d ,)"
  docker compose version >/dev/null 2>&1 && ok "compose plugin present" \
    || bad "docker compose plugin missing"
else
  bad "docker not installed"
fi

# A preflight that stops at the first missing tool is not a preflight. Every
# probe below tolerates an absent command and reports it, so one run lists
# everything that is wrong rather than the first thing.
have() { command -v "$1" >/dev/null 2>&1; }

# RAM is this box's ceiling, not disk — capacity-check.sh says so.
if have free; then
  mem_avail=$(free -m | awk '/^Mem:/{print $7}')
  if (( mem_avail > 2048 )); then ok "RAM available ${mem_avail}MB (needs ~400MB)"
  else bad "RAM available ${mem_avail}MB is too tight"; fi
else
  bad "free(1) not found — this does not look like the box"
fi

if have df; then
  disk_pct=$(df --output=pcent / | tail -1 | tr -dc '0-9')
  disk_free=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
  if (( disk_pct < 80 )); then ok "disk ${disk_pct}% used, ${disk_free}GB free (needs ~2GB)"
  else bad "disk ${disk_pct}% used — over the 80% floor"; fi
else
  bad "df(1) not found"
fi

if ! have ss; then
  warn "ss(1) not found — cannot tell whether port ${PORT} is free"
elif ss -ltn 2>/dev/null | grep -q ":${PORT}[[:space:]]"; then
  if docker ps --format '{{.Names}}\t{{.Ports}}' | grep -q ":${PORT}->"; then
    warn "port ${PORT} already held by this service — this is a redeploy"
  else
    bad "port ${PORT} is in use by something else"
  fi
else
  ok "port ${PORT} free"
fi

if [[ -f "${APP_DIR}/docker-compose.yml" ]]; then
  ok "compose file present"
  if grep -qE '^\s{2}calories:' "${APP_DIR}/docker-compose.yml"; then
    ok "'calories' service defined"
  else
    bad "'calories' service not in ${APP_DIR}/docker-compose.yml — add it first (docs/deploy-contabo.md §3)"
  fi
  # The mistake that took the site down: a volume over the image's own data dir.
  if grep -qE ':/app/data' "${APP_DIR}/docker-compose.yml"; then
    bad "a volume mounts over /app/data — that hides site.db and 502s every route"
  else
    ok "nothing mounted over /app/data"
  fi
  # The house rule: bind loopback, never publish.
  if grep -E "\"[0-9.]*:?${PORT}:8000\"" "${APP_DIR}/docker-compose.yml" | grep -qv '127.0.0.1'; then
    bad "port ${PORT} is published beyond 127.0.0.1"
  else
    ok "port bound to 127.0.0.1 only"
  fi
else
  bad "${APP_DIR}/docker-compose.yml not found"
fi

if [[ -f "${ENV_FILE}" ]]; then
  perms=$(stat -c '%a' "${ENV_FILE}")
  [[ "${perms}" == "600" ]] && ok ".env is 0600" || bad ".env is ${perms}, should be 600"
  for key in SITE_DOMAIN_JA SITE_CACHE_MAX_AGE; do
    grep -q "^${key}=" "${ENV_FILE}" && ok "${key} set" || bad "${key} missing from .env"
  done
  # Without this the site sends no-cache on all 4,000 pages and Cloudflare
  # forwards every hit, which is how it behaved for weeks.
  grep -q '^SITE_CACHE_MAX_AGE=[1-9]' "${ENV_FILE}" \
    && ok "caching enabled" || warn "SITE_CACHE_MAX_AGE is 0 or unset — every page will be uncached"
  for key in WP_URL WP_HOST WP_WEBHOOK_SECRET BLOG_DB_PATH; do
    grep -q "^${key}=" "${ENV_FILE}" && ok "${key} set (blog)" || warn "${key} unset — /column renders empty"
  done
else
  bad "${ENV_FILE} not found (docs/deploy-contabo.md §2)"
fi

if [[ "${fail}" -ne 0 ]]; then
  printf '\n\033[31mpreflight failed — nothing was changed\033[0m\n'
  exit 1
fi
printf '\n\033[32mpreflight clean\033[0m\n'

[[ "${VERIFY_ONLY}" -eq 1 ]] || true

# ------------------------------------------------------------------- fetch
if [[ "${VERIFY_ONLY}" -eq 0 ]]; then
  step "Fetch"
  if [[ -d "${SRC_DIR}/.git" ]]; then
    would "git -C ${SRC_DIR} pull --ff-only"
  else
    would "install -d -m 755 ${APP_DIR}/calories"
    would "git clone ${REPO} ${SRC_DIR}"
  fi

  # --------------------------------------------------------------- build/up
  step "Build and start"
  # Built before the running container is touched, so a broken build cannot
  # replace a working site.
  would "docker compose --project-directory ${APP_DIR} build ${SERVICE}"
  would "docker compose --project-directory ${APP_DIR} up -d ${SERVICE}"
fi

# ------------------------------------------------------------------ verify
step "Verify"
if [[ "${DRY_RUN}" -eq 1 && "${VERIFY_ONLY}" -eq 0 ]]; then
  echo "  would: wait for the container to answer, then curl the routes below"
  echo "         /robots.txt /menu /column /dish/… /sitemap.xml"
  printf '\n\033[1mDry run only. Nothing was changed.\033[0m\n'
  printf 'Re-run with --apply when the preflight above is clean.\n'
  exit 0
fi

printf '  waiting for the container to answer'
for _ in $(seq 1 30); do
  if curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/robots.txt" 2>/dev/null; then
    printf '\n'; ok "container is serving"; break
  fi
  printf '.'; sleep 2
done

if ! curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/robots.txt" 2>/dev/null; then
  printf '\n'
  bad "container is not answering — it has not replaced anything public yet"
  echo
  echo "  Read the reason and stop here:"
  echo "    docker compose --project-directory ${APP_DIR} logs --tail=40 ${SERVICE}"
  exit 1
fi

for path in / /menu /nutrients /cooking-yield /api /embed /column /foods /analyzer /sitemap.xml; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}${path}")
  [[ "${code}" == "200" ]] && ok "${code}  ${path}" || bad "${code}  ${path}"
done
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/blog")
[[ "${code}" == "301" ]] && ok "301  /blog redirects to /column" || warn "${code}  /blog (expected 301)"

cache=$(curl -s -D - -o /dev/null "http://127.0.0.1:${PORT}/" | grep -i '^cache-control' || true)
grep -q 'max-age=[1-9]' <<<"${cache}" && ok "caching on:${cache#*:}" \
  || warn "no cache header — set SITE_CACHE_MAX_AGE in ${ENV_FILE}"

if [[ "${fail}" -ne 0 ]]; then
  printf '\n\033[31mverification failed — do not point DNS at this box yet\033[0m\n'
  exit 1
fi
printf '\n\033[32mall checks passed\033[0m\n'
printf 'Next: CloudPanel reverse proxy to http://127.0.0.1:%s, then move the DNS.\n' "${PORT}"
printf 'Railway keeps serving until that DNS change, so rollback is one record.\n'
