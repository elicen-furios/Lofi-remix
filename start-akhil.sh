#!/data/data/com.termux/files/usr/bin/bash

clear

CYAN='\033[1;36m'
RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
RESET='\033[0m'

echo -e "${CYAN}"
cat << 'BANNER'
░█████╗░██╗░░██╗██╗░░██╗██╗██╗░░░░░
██╔══██╗██║░░██╔╝██║░░██║██║██║░░░░░
███████║█████═╝░███████║██║██║░░░░░
██╔══██╗██╔═██╗░██╔══██║██║██║░░░░░
██║░░██║██║░╚██╗██║░░██║██║███████╗
╚═╝░░╚═╝╚═╝░░╚═╝╚═╝░░╚═╝╚═╝╚══════╝
BANNER
echo -e "${RESET}"

echo -e "${RED}       [ AKHIL AUDIO SYSTEM ]${RESET}"
echo -e "${CYAN}========================================${RESET}"

read -rsp "Enter Password: " PASS
echo

if [[ "$PASS" != "8630" ]]; then
    echo -e "${RED}[ACCESS DENIED] Wrong password!${RESET}"
    exit 1
fi

echo -e "${GREEN}[ACCESS GRANTED] Welcome to AKHIL AUDIO!${RESET}"

for i in 10 25 40 55 70 85 100; do
    printf "\r${CYAN}[%-20s] %s%%${RESET}" \
        "$(printf '%*s' "$((i / 5))" '' | tr ' ' '#')" "$i"
    sleep 0.15
done

echo
echo

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "FFmpeg missing. Run: pkg install ffmpeg"
    exit 1
fi

if [ ! -f service.py ] || [ ! -f index.html ]; then
    echo "Project files missing!"
    exit 1
fi

echo -e "${YELLOW}Installing dependencies...${RESET}"

if [ -f requirements.txt ]; then
    python -m pip install -r requirements.txt || exit 1
fi

echo -e "${GREEN}Starting AKHIL AUDIO WEB...${RESET}"
echo "Open: http://127.0.0.1:5000"
echo "Press CTRL+C to stop."

exec python service.py
