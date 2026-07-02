#!/usr/bin/env bash
set -euo pipefail

# Restrict G1 control ports so only the Tongyu central hub can reach them.
# Usage:
#   sudo bash scripts/linux/g1_allow_only_central.sh 192.168.1.50 8080 8081
#
# Keep SSH open before applying the robot-control restrictions. Replace the
# port list with the actual Unitree SDK / bridge ports found by:
#   sudo ss -lntup

CENTRAL_IP="${1:-192.168.1.50}"
shift || true
CONTROL_PORTS=("$@")

if [[ ${#CONTROL_PORTS[@]} -eq 0 ]]; then
  echo "Usage: sudo bash $0 <central_ip> <control_port> [control_port...]"
  echo "Example: sudo bash $0 192.168.1.50 8080 8731"
  exit 2
fi

if ! command -v ufw >/dev/null 2>&1; then
  echo "ufw is required. Install with: sudo apt-get update && sudo apt-get install -y ufw"
  exit 1
fi

echo "Central hub IP: ${CENTRAL_IP}"
echo "Control ports: ${CONTROL_PORTS[*]}"

sudo ufw allow OpenSSH
sudo ufw default deny incoming
sudo ufw default allow outgoing

for port in "${CONTROL_PORTS[@]}"; do
  sudo ufw allow from "${CENTRAL_IP}" to any port "${port}" proto tcp
  sudo ufw deny "${port}"/tcp
done

sudo ufw --force enable
sudo ufw status numbered

echo "Done. Only ${CENTRAL_IP} should reach the listed G1 control ports."
