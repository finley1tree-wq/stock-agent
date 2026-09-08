#!/bin/bash
# Double-click me on your Mac. Installs everything, asks for your keys, writes .env, and runs a check.
cd "$(dirname "$0")"
echo "== Stock agent setup =="
if ! command -v python3 >/dev/null; then echo "Install Python 3 first: https://www.python.org/downloads/"; read -p "Press enter to exit"; exit 1; fi
python3 -m pip install -q -r requirements.txt --user 2>/dev/null || python3 -m pip install -q -r requirements.txt --break-system-packages

if [ ! -f .env ]; then
  echo
  echo "The agent starts in SIM mode: a pretend \$400 portfolio, real prices, buys and sells, no brokerage needed."
  echo "Only the Anthropic key is required. Paste each key and press enter; press enter alone to skip optional ones."
  echo
  read -p "Anthropic API key (required): " AN
  read -p "Financial Modeling Prep key (optional, Congress + insider feeds): " FM
  read -p "Alpaca API key (optional, only for Alpaca paper later): " AK
  read -p "Alpaca secret key (optional): " AS
  read -p "Quiver Quant key (optional): " QV
  cat > .env <<ENV
# Which broker the agent trades through: sim (pretend money, default) | alpaca | ibkr
BROKER=sim

ANTHROPIC_API_KEY=$AN
ANTHROPIC_MODEL=claude-sonnet-5

FMP_API_KEY=$FM
QUIVER_API_KEY=$QV

# Alpaca (only used when BROKER=alpaca)
ALPACA_API_KEY=$AK
ALPACA_SECRET_KEY=$AS
ALPACA_PAPER=true
DRY_RUN=true
ENV
  chmod 600 .env; echo ".env written (BROKER=sim)."
fi

# Existing .env: offer to fill empty keys or replace any key (enter = keep).
ask_key () {  # $1 var name, $2 prompt text
  if grep -q "^$1=$" .env; then
    read -p "$2 (enter to skip): " V
    [ -n "$V" ] && sed -i '' "s|^$1=$|$1=$V|" .env && echo "$1 saved."
  else
    read -p "$2 (enter to keep current): " V
    [ -n "$V" ] && sed -i '' "s|^$1=.*|$1=$V|" .env && echo "$1 replaced."
  fi
}
echo
ask_key ANTHROPIC_API_KEY "Anthropic API key (required)"
ask_key FMP_API_KEY "Financial Modeling Prep key (optional)"
ask_key QUIVER_API_KEY "Quiver Quant key (optional, paid Congress feed)"

echo; echo "== Check =="
python3 -m agent.run --report && echo && echo "Working. Next: run.command during market hours (6:30 AM–1:00 PM Pacific, weekdays), or autopilot-mac.command to run it every 30 minutes automatically." || echo "Something failed above — send that error to Claude."
read -p "Press enter to close"
