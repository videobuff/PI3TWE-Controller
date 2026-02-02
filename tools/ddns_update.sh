#!/bin/bash

DOMAIN="pi3twe"
TOKEN="a3103069-6f2a-4c6f-93a5-8f230cdf896a"

# bepaal actief extern IP
IP=$(ip route get 1.1.1.1 | awk '{print $7}')

curl -fsS "https://www.duckdns.org/update?domains=${DOMAIN}&token=${TOKEN}&ip=${IP}" \
  && echo "$(date -Is) DDNS OK ${IP}" \
  || echo "$(date -Is) DDNS FAIL"
