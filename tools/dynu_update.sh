#!/bin/bash
set -e

USERNAME="JOUW_DYNU_USERNAME"
PASSWORD_MD5="JOUW_MD5_HASH"
HOSTNAME="tvvpn.dynu.net"

# haal actuele IP’s op
IPV4=$(curl -4 -fsS https://api.ipify.org)
IPV6=$(curl -6 -fsS https://api64.ipify.org || true)

URL="https://api.dynu.com/nic/update?hostname=${HOSTNAME}&myip=${IPV4}"

if [ -n "$IPV6" ]; then
  URL="${URL}&myipv6=${IPV6}"
fi

URL="${URL}&username=${videobuff}&password=${Stt1951_mrs}"

curl -fsS "$URL" >/dev/null \
  && echo "$(date -Is) DYNU OK v4=${IPV4} v6=${IPV6}" \
  || echo "$(date -Is) DYNU FAIL"
