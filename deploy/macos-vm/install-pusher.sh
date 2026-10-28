#!/usr/bin/env bash
# Install pusher/ into the macOS guest over SSH (the guest needs Remote Login on), using uv's
# standalone python: macOS's /usr/bin/python3 is only a stub until the Xcode tools are installed.
# Usage: deploy/macos-vm/install-pusher.sh <guest-user> [ssh host] [ssh port]
#   defaults: host 127.0.0.1, port 2222 (compose.yml's forward). Reads ./pusher.env next to this
#   script (MONEY_URL, MONEY_TOKEN, MONEY_MIN_SMS; mode 600, gitignored).
# Afterwards give the python it prints Full Disk Access in the guest (README.md here).
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
user=${1:?usage: install-pusher.sh <guest-user> [host] [port]}
host=${2:-127.0.0.1}
port=${3:-2222}
[ -f "$here/pusher.env" ] || { echo "missing $here/pusher.env" >&2; exit 1; }
ssh=(ssh -p "$port" "$user@$host")
"${ssh[@]}" 'mkdir -p ~/money-coach/pusher ~/.config/money-coach && chmod 700 ~/.config/money-coach'
scp -P "$port" "$here"/../../pusher/{push.py,export_sms.py,install-macos.sh} "$user@$host:money-coach/pusher/"
scp -P "$port" "$here/pusher.env" "$user@$host:.config/money-coach/pusher.env"
"${ssh[@]}" 'set -e
chmod 600 ~/.config/money-coach/pusher.env
[ -x ~/.local/bin/uv ] || curl -LsSf https://astral.sh/uv/install.sh | sh
~/.local/bin/uv python install 3.12
py=$(realpath "$(~/.local/bin/uv python find --managed-python 3.12)")
bash ~/money-coach/pusher/install-macos.sh "$py"'
