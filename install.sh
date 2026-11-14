#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#  TG Leech Bot — installer / manager
#  Run:  bash <(curl -fsSL https://raw.githubusercontent.com/YOUR_USER/tgbot/main/install.sh)
#  Menu: install · update · edit config · uninstall
# ──────────────────────────────────────────────────────────────
set -uo pipefail

REPO_SLUG="${REPO_SLUG:-YOUR_USER/tgbot}"
REPO_URL="${REPO_URL:-https://github.com/${REPO_SLUG}.git}"
BRANCH="${BRANCH:-main}"
SERVICE="tgbot"
DEFAULT_DIR="${INSTALL_DIR:-$HOME/tgbot}"

# ── colors / output ───────────────────────────────────────────
if [ -t 1 ]; then
  R=$'\033[0m'; B=$'\033[1m'; D=$'\033[2m'
  RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; CYN=$'\033[36m'; MAG=$'\033[35m'
else
  R=""; B=""; D=""; RED=""; GRN=""; YEL=""; CYN=""; MAG=""
fi
step() { printf '\n%s%s▶ %s%s\n' "$CYN" "$B" "$*" "$R"; }
ok()   { printf '  %s✔%s %s\n' "$GRN" "$R" "$*"; }
warn() { printf '  %s!%s %s\n' "$YEL" "$R" "$*"; }
info() { printf '  %s%s%s\n' "$D" "$*" "$R"; }
die()  { printf '\n  %s✘ %s%s\n\n' "$RED" "$*" "$R" >&2; exit 1; }

banner() {
  printf '\n%s%s' "$MAG" "$B"
  printf '   ┌─────────────────────────────────────────┐\n'
  printf '   │   TG Leech Bot  ·  Telegram → GitHub    │\n'
  printf '   └─────────────────────────────────────────┘\n'
  printf '%s\n' "$R"
}

# ── helpers ───────────────────────────────────────────────────
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi
if [ -r /dev/tty ] && [ -w /dev/tty ]; then TTY=/dev/tty; else TTY=""; fi

SELF="${BASH_SOURCE[0]:-}"
SELF_DIR=""
if [ -n "$SELF" ] && [ -f "$SELF" ]; then SELF_DIR="$(cd "$(dirname "$(readlink -f "$SELF")")" && pwd)"; fi

INSTALL_DIR=""
resolve_dir() {
  if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/main.py" ]; then INSTALL_DIR="$SELF_DIR"
  else INSTALL_DIR="$DEFAULT_DIR"; fi
}

confirm() {  # confirm "question" [default y|n]
  local q="$1" def="${2:-n}" ans hint="[y/N]"
  [ "$def" = y ] && hint="[Y/n]"
  if [ -z "$TTY" ]; then [ "$def" = y ]; return; fi
  read -rp "  ${q} ${hint} " ans < "$TTY" || ans=""
  ans="${ans:-$def}"
  [[ "$ans" =~ ^[Yy] ]]
}

need_tty() { [ -n "$TTY" ] || die "No terminal available for questions. Pass values as env vars instead (API_ID=… BOT_TOKEN=… bash install.sh install)."; }

service_exists() { [ -f "/etc/systemd/system/${SERVICE}.service" ]; }
is_installed()   { [ -f "$INSTALL_DIR/main.py" ] && [ -d "$INSTALL_DIR/venv" ]; }

# ── .env handling ─────────────────────────────────────────────
load_env() {
  local file="$1" k v
  [ -f "$file" ] || return 0
  while IFS='=' read -r k v; do
    [[ "$k" =~ ^[A-Z_]+$ ]] || continue
    printf -v "$k" '%s' "$v"
  done < "$file"
}

mask() { local v="$1"; if [ "${#v}" -gt 8 ]; then printf '%s…%s' "${v:0:4}" "${v: -3}"; else printf '****'; fi; }

ask() {  # ask VAR "Label" "hint" regex secret(0|1)
  local name="$1" label="$2" hint="$3" regex="$4" secret="${5:-0}" cur val shown
  cur="${!name:-}"
  while true; do
    printf '\n  %s%s%s\n' "$B" "$label" "$R"
    [ -n "$hint" ] && info "$hint"
    shown=""
    if [ -n "$cur" ]; then
      if [ "$secret" = 1 ]; then shown=" [$(mask "$cur")]"; else shown=" [$cur]"; fi
    fi
    if [ "$secret" = 1 ]; then
      read -rsp "  › ${name}${shown}: " val < "$TTY" || die "Input closed."; echo
    else
      read -rp "  › ${name}${shown}: " val < "$TTY" || die "Input closed."
    fi
    val="${val:-$cur}"
    if [[ "$val" =~ $regex ]]; then printf -v "$name" '%s' "$val"; return; fi
    warn "That value doesn't look right. Try again."
  done
}

collect_config() {
  need_tty
  step "Configuration"
  info "Press Enter to keep the value shown in [brackets]."
  ask API_ID "Telegram API ID" "Get it at https://my.telegram.org → API development tools" '^[0-9]+$'
  ask API_HASH "Telegram API Hash" "Same page as the API ID (32 hex characters)" '^[0-9a-fA-F]{32}$' 1
  ask BOT_TOKEN "Bot token" "Create a bot with @BotFather and paste the token" '^[0-9]{6,}:[A-Za-z0-9_-]{30,}$' 1
  ask ADMIN_ID "Your numeric Telegram user ID" "Send /start to @userinfobot to see it. Only this user can use the bot." '^[0-9]+$'
  ask GITHUB_TOKEN "GitHub token" "Classic token with 'repo' scope, or fine-grained with Contents: Read and write" '^[A-Za-z0-9_]{20,}$' 1
  ask GITHUB_REPO "GitHub repo for uploads (owner/name)" "Releases are created here. The repo needs at least one commit." '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'
}

verify_config() {
  step "Checking credentials"
  local resp name code tmp
  resp=$(curl -fsS --max-time 15 "https://api.telegram.org/bot${BOT_TOKEN}/getMe" 2>/dev/null || true)
  if echo "$resp" | grep -q '"ok":true'; then
    name=$(echo "$resp" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["username"])' 2>/dev/null || echo "?")
    ok "Telegram bot token is valid (@${name})"
  else
    warn "Telegram rejected the bot token."
    confirm "Continue anyway?" n || die "Aborted."
  fi

  tmp=$(mktemp)
  code=$(curl -s -o "$tmp" -w '%{http_code}' --max-time 15 \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${GITHUB_REPO}" || echo 000)
  case "$code" in
    200)
      if python3 -c 'import sys,json; sys.exit(0 if json.load(open(sys.argv[1])).get("permissions",{}).get("push") else 1)' "$tmp" 2>/dev/null; then
        ok "GitHub repo ${GITHUB_REPO} is reachable and writable"
      else
        warn "Token can read ${GITHUB_REPO} but may not be able to write to it."
      fi
      code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
        -H "Authorization: Bearer ${GITHUB_TOKEN}" "https://api.github.com/repos/${GITHUB_REPO}/commits?per_page=1" || echo 000)
      if [ "$code" = 409 ]; then warn "Repo is empty — add a README commit first, or release creation will fail."; fi
      ;;
    401) warn "GitHub rejected the token (401)."; confirm "Continue anyway?" n || die "Aborted." ;;
    404) warn "Repo ${GITHUB_REPO} not found, or the token has no access to it."; confirm "Continue anyway?" n || die "Aborted." ;;
    *)   warn "Could not verify GitHub (HTTP ${code})." ;;
  esac
  rm -f "$tmp"
}

write_env() {
  local quality="${DEFAULT_QUALITY:-720}" clients="${YT_CLIENTS:-}"
  ( umask 077
    cat > "$INSTALL_DIR/.env" <<ENV_FILE
API_ID=${API_ID}
API_HASH=${API_HASH}
BOT_TOKEN=${BOT_TOKEN}
ADMIN_ID=${ADMIN_ID}
GITHUB_TOKEN=${GITHUB_TOKEN}
GITHUB_REPO=${GITHUB_REPO}

# optional
DEFAULT_QUALITY=${quality}
YT_CLIENTS=${clients}
ENV_FILE
  )
  chmod 600 "$INSTALL_DIR/.env"
  ok "Saved $INSTALL_DIR/.env (permissions 600)"
}

# ── installation steps ────────────────────────────────────────
check_os() {
  step "Checking system"
  if [ -r /etc/os-release ]; then . /etc/os-release; ok "${PRETTY_NAME:-unknown OS}"; fi
  command -v apt-get >/dev/null || die "This installer supports Debian/Ubuntu (apt) only."
  if [ -n "$SUDO" ]; then command -v sudo >/dev/null || die "sudo is required (or run as root)."; fi
}

install_packages() {
  step "Installing system packages"
  $SUDO apt-get update -qq
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3 python3-venv python3-pip python3-dev build-essential \
    ffmpeg p7zip-full megatools git curl unzip ca-certificates >/dev/null
  ok "python3, ffmpeg, 7-Zip, megatools, git"
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "Python 3.10+ is required."

  if ! command -v deno >/dev/null; then
    info "Installing deno (needed by yt-dlp for YouTube)…"
    if curl -fsSL https://deno.land/install.sh | $SUDO env DENO_INSTALL=/usr/local sh -s -- --no-modify-path >/dev/null 2>&1; then
      ok "deno installed"
    else
      warn "deno install failed — YouTube may fail until you install it manually."
    fi
  else
    ok "deno already installed"
  fi
}

fetch_code() {
  step "Getting the bot code"
  if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/main.py" ]; then
    INSTALL_DIR="$SELF_DIR"; ok "Using $INSTALL_DIR"; return
  fi
  if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" pull --ff-only -q && ok "Updated $INSTALL_DIR"
  else
    if [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then die "$INSTALL_DIR exists and is not empty."; fi
    git clone -q -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR" || die "git clone failed. Check REPO_SLUG / REPO_URL ($REPO_URL)."
    ok "Cloned into $INSTALL_DIR"
  fi
}

setup_python() {
  step "Setting up Python environment"
  cd "$INSTALL_DIR" || die "Cannot enter $INSTALL_DIR"
  [ -d venv ] || python3 -m venv venv
  ./venv/bin/pip install -q -U pip
  ./venv/bin/pip install -q -r requirements.txt || die "pip install failed."
  ./venv/bin/python -c 'import pyrogram, yt_dlp, httpx' || die "Python packages did not install correctly."
  mkdir -p cookies
  ok "Dependencies installed"
}

install_service() {
  step "Installing systemd service"
  sed -e "s|__USER__|${SUDO_USER:-$(id -un)}|" -e "s|__DIR__|${INSTALL_DIR}|g" "$INSTALL_DIR/tgbot.service" \
    | $SUDO tee "/etc/systemd/system/${SERVICE}.service" >/dev/null
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable "$SERVICE" >/dev/null 2>&1
  $SUDO chmod +x "$INSTALL_DIR/install.sh"
  $SUDO ln -sf "$INSTALL_DIR/install.sh" /usr/local/bin/tgbot
  ok "Service '${SERVICE}' enabled · command 'tgbot' is now available"
}

restart_service() {
  $SUDO systemctl restart "$SERVICE"
  sleep 3
  if systemctl is-active --quiet "$SERVICE"; then ok "Bot is running"
  else warn "Bot is not running — see: journalctl -u ${SERVICE} -n 50"; fi
}

# ── actions ───────────────────────────────────────────────────
do_install() {
  banner
  resolve_dir
  if is_installed && service_exists; then
    warn "Already installed in $INSTALL_DIR."
    confirm "Reinstall dependencies and reconfigure?" n || return 0
  fi
  check_os
  install_packages
  fetch_code
  load_env "$INSTALL_DIR/.env"
  if [ -z "$TTY" ] && [ -n "${API_ID:-}" ] && [ -n "${BOT_TOKEN:-}" ]; then
    info "Using values from environment/.env (non-interactive)."
  else
    collect_config
  fi
  verify_config
  write_env
  setup_python
  install_service
  step "Starting the bot"
  restart_service
  done_box
}

do_update() {
  banner
  resolve_dir
  is_installed || die "Bot is not installed in $INSTALL_DIR. Run the install option first."
  step "Updating"
  cd "$INSTALL_DIR" || die "Cannot enter $INSTALL_DIR"
  local before after
  before=$(git rev-parse HEAD)
  git pull --ff-only -q || die "git pull failed (local changes?). Try: cd $INSTALL_DIR && git stash"
  after=$(git rev-parse HEAD)
  if [ "$before" = "$after" ]; then
    ok "Already up to date ($(git rev-parse --short HEAD))"
  else
    ok "Updated to $(git rev-parse --short HEAD):"
    git --no-pager log --oneline "$before..$after" | head -10 | sed 's/^/      /'
    ./venv/bin/pip install -q -r requirements.txt
    install_service
    restart_service
  fi
  info "Tip: refresh only yt-dlp any time with:  tgbot ytdlp"
}

do_ytdlp() {
  resolve_dir
  step "Upgrading yt-dlp"
  "$INSTALL_DIR/venv/bin/pip" install -q -U "yt-dlp[default]" && ok "yt-dlp $("$INSTALL_DIR/venv/bin/python" -m yt_dlp --version)"
  restart_service
}

do_config() {
  banner
  resolve_dir
  is_installed || die "Bot is not installed yet."
  load_env "$INSTALL_DIR/.env"
  collect_config
  verify_config
  write_env
  step "Restarting"
  restart_service
}

do_uninstall() {
  banner
  resolve_dir
  step "Uninstall"
  warn "This stops the service and removes the systemd unit and the 'tgbot' command."
  confirm "Continue?" n || { info "Cancelled."; return 0; }
  $SUDO systemctl disable --now "$SERVICE" 2>/dev/null || true
  $SUDO rm -f "/etc/systemd/system/${SERVICE}.service" /usr/local/bin/tgbot
  $SUDO systemctl daemon-reload
  ok "Service removed"
  if [ -d "$INSTALL_DIR" ]; then
    warn "$INSTALL_DIR contains your .env, cookies and Telegram session."
    if confirm "Delete $INSTALL_DIR completely?" n; then
      cd / && rm -rf "$INSTALL_DIR" && ok "Deleted $INSTALL_DIR"
    else
      info "Kept $INSTALL_DIR"
    fi
  fi
  ok "Uninstalled"
}

do_status() {
  systemctl status "$SERVICE" --no-pager -l 2>/dev/null | head -14 || warn "Service not installed."
}

do_logs() { journalctl -u "$SERVICE" -n "${1:-80}" -f --no-pager; }

done_box() {
  printf '\n%s%s' "$GRN" "$B"
  printf '  ╭──────────────────────────────────────────────╮\n'
  printf '  │  ✔ Installed. Open your bot in Telegram and  │\n'
  printf '  │    send /start                               │\n'
  printf '  ╰──────────────────────────────────────────────╯\n'
  printf '%s\n' "$R"
  printf '  Manage anytime with:\n'
  printf '    %stgbot%s            interactive menu\n' "$B" "$R"
  printf '    %stgbot update%s     update code + dependencies\n' "$B" "$R"
  printf '    %stgbot config%s     edit variables (token, repo, …)\n' "$B" "$R"
  printf '    %stgbot logs%s       live logs\n' "$B" "$R"
  printf '    %stgbot restart%s    restart the bot\n\n' "$B" "$R"
}

menu() {
  banner
  resolve_dir
  need_tty
  local state="not installed" choice
  if is_installed; then state="installed · $(systemctl is-active "$SERVICE" 2>/dev/null || echo stopped)"; fi
  printf '  %sStatus:%s %s   %s(%s)%s\n\n' "$B" "$R" "$state" "$D" "$INSTALL_DIR" "$R"
  printf '    %s1)%s Install\n' "$B" "$R"
  printf '    %s2)%s Update\n' "$B" "$R"
  printf '    %s3)%s Edit config (tokens, repo, …)\n' "$B" "$R"
  printf '    %s4)%s Uninstall\n' "$B" "$R"
  printf '    %s5)%s Logs\n' "$B" "$R"
  printf '    %s0)%s Exit\n\n' "$B" "$R"
  read -rp "  Choose [0-5]: " choice < "$TTY" || exit 0
  case "$choice" in
    1) do_install ;;
    2) do_update ;;
    3) do_config ;;
    4) do_uninstall ;;
    5) do_logs ;;
    *) exit 0 ;;
  esac
}

usage() {
  printf 'Usage: tgbot [command]\n\n'
  printf '  install      install the bot (asks for tokens)\n'
  printf '  update       pull the latest code, update dependencies, restart\n'
  printf '  config       edit the variables in .env and restart\n'
  printf '  uninstall    remove the service (optionally the files)\n'
  printf '  ytdlp        upgrade yt-dlp only\n'
  printf '  start|stop|restart|status|logs\n'
  printf '  (no command) interactive menu\n'
}

case "${1:-menu}" in
  menu)               menu ;;
  install)            do_install ;;
  update)             do_update ;;
  config|edit)        do_config ;;
  uninstall|remove)   do_uninstall ;;
  ytdlp)              do_ytdlp ;;
  start|stop|restart) resolve_dir; $SUDO systemctl "$1" "$SERVICE" && echo "ok" ;;
  status)             do_status ;;
  logs)               shift; do_logs "${1:-80}" ;;
  -h|--help|help)     usage ;;
  *)                  usage; exit 1 ;;
esac
