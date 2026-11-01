#!/data/data/com.termux/files/usr/bin/bash

# ==========================================
# AKHIL AUDIO | CYBERPUNK TERMINAL
# ==========================================

export TERM="${TERM:-xterm-256color}"

R='\033[1;31m'
C='\033[1;36m'
G='\033[1;32m'
Y='\033[1;33m'
W='\033[1;37m'
D='\033[2;90m'
B='\033[1m'
N='\033[0m'

trap 'printf "\n%b[ SYSTEM HALTED ]%b\n" "$R" "$N"' INT

clear

printf "${R}"
cat <<'BANNER'

     ▄█████▄  ██ ▄█▀ ██░ ██  ██▓ ██▓
    ▒██▀ ██▌ ██▄█▒ ▓██░ ██▒▓██▒▓██▒
    ░██   █▌▓███▄░ ▒██▀▀██░▒██▒▒██▒
    ░▓█▄   ▌▓██ █▄ ░▓█ ░██ ░██░░██░
    ░▒████▓ ▒██▒ █▄░▓█▒░██▓░██░░██░
     ▒▒▓  ▒ ▒ ▒▒ ▓▒ ▒ ░░▒░▒░▓  ░▓
     ░ ▒  ▒ ░ ░▒ ▒░ ▒ ░▒░ ░ ▒ ░ ▒ ░
     ░ ░  ░ ░ ░░ ░  ░  ░░ ░ ▒ ░ ▒ ░

BANNER
printf "${N}"

printf "${C}  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${N}\n"
printf "${C}  ┃${R}       A K H I L   A U D I O          ${C}┃${N}\n"
printf "${C}  ┃${D}         DARK SYSTEM  /  v2.0         ${C}┃${N}\n"
printf "${C}  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${N}\n\n"

printf "${R}  [ ! ]${W} AUTHORIZED ACCESS REQUIRED${N}\n"
printf "${D}  ──────────────────────────────────────${N}\n"

read -rsp "$(printf "${C}  ROOT PASSWORD  ${R}>> ${N}")" PASS
printf "\n"

if [[ "$PASS" != "8630" ]]; then
    printf "\n${R}  ╔══════════════════════════════════════╗${N}\n"
    printf "${R}  ║         ACCESS DENIED  [X]           ║${N}\n"
    printf "${R}  ╚══════════════════════════════════════╝${N}\n\n"
    unset PASS
    exit 1
fi

unset PASS

printf "\n${G}  [ OK ] ACCESS GRANTED${N}\n"
printf "${D}  Initializing audio subsystem...${N}\n\n"

spin='|/-\'
for i in $(seq 1 24); do
    c="${spin:$((i % 4)):1}"
    printf "\r${R}  [${C}%s${R}]${W} Establishing secure session... ${C}%02d%%${N}" "$c" "$((i * 100 / 24))"
    sleep 0.07
done

printf "\r${G}  [ OK ] Session initialized                    ${N}\n\n"

if ! command -v python >/dev/null 2>&1; then
    printf "${R}  [ ERROR ] Python is not installed.${N}\n"
    printf "${Y}  Run: pkg install python -y${N}\n"
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    printf "${R}  [ ERROR ] FFmpeg is missing.${N}\n"
    printf "${Y}  Run: pkg install ffmpeg -y${N}\n"
    exit 1
fi

if [[ ! -f service.py || ! -f index.html ]]; then
    printf "${R}  [ ERROR ] Project files not found.${N}\n"
    exit 1
fi

printf "${C}  [ 1/3 ]${W} Checking system dependencies...${N}\n"

if [[ -f requirements.txt ]]; then
    printf "${C}  [ 2/3 ]${W} Preparing Python environment...${N}\n"

    if ! python -m pip install -r requirements.txt -q > "$HOME/.akhil-install.log" 2>&1; then
        printf "\n${R}  [ ERROR ] Dependency installation failed.${N}\n"
        printf "${Y}  Details: cat ~/.akhil-install.log${N}\n"
        exit 1
    fi
fi

printf "${G}  [ OK ] Dependencies ready${N}\n\n"

printf "${R}  ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${N}\n"
printf "${R}  ┃${W}          SYSTEM ONLINE                ${R}┃${N}\n"
printf "${R}  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${N}\n\n"

printf "${C}  WEB PANEL  ${W}http://127.0.0.1:5000${N}\n"
printf "${C}  ENGINE     ${W}FFmpeg Audio Processing${N}\n"
printf "${C}  MODE       ${G}LOCAL DEVICE${N}\n"
printf "${D}  ──────────────────────────────────────${N}\n"
printf "${Y}  Keep this terminal open while using the site.${N}\n"
printf "${Y}  Press CTRL+C to stop the server.${N}\n\n"

exec python service.py
