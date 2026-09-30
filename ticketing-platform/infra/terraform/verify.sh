#!/usr/bin/env bash
# Post-deploy verification for the Week 4 AWS landing — the [Claude] step of
# the deploy flow (WEEK4_DESIGN §5 / README step 7). Read-only health checks
# through the ALB + one optional booking-path probe. Exits non-zero if a
# health check fails, so it can gate a deploy.
#
# Usage:  ALB=<alb-dns-name> ./verify.sh      (or)      ./verify.sh <alb-dns-name>
# The ALB DNS comes from `terraform output alb_dns_name` after Rajat applies.
set -uo pipefail

ALB="${1:-${ALB:-}}"
if [[ -z "$ALB" ]]; then
  echo "usage: ALB=<alb-dns-name> $0    (or)    $0 <alb-dns-name>" >&2
  echo "  get it from: terraform output -raw alb_dns_name" >&2
  exit 2
fi
BASE="http://${ALB}"
fail=0

check_health() {
  local name="$1" path="$2" body
  body=$(curl -fsS --max-time 10 "${BASE}${path}" 2>/dev/null) || body=""
  if echo "$body" | grep -q '"status":"UP"'; then
    echo "  [ok]   ${name} health: UP"
  else
    echo "  [FAIL] ${name} health at ${BASE}${path}"
    echo "         ${body:-<no response>}"
    fail=1
  fi
}

echo "Verifying ticketing on ${BASE}"
check_health "inventory" "/api/inventory/actuator/health"
check_health "booking"   "/api/booking/actuator/health"

echo ""
echo "Booking-path probe (POST /api/booking/bookings) — response printed, not asserted"
echo "(needs seed seat data; a clean failure here is fine on a fresh DB):"
curl -sS --max-time 15 -X POST "${BASE}/api/booking/bookings" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: verify-$(date +%s)" \
  -d '{"showId":1,"seatIds":[1],"holderId":"verify-user"}' 2>/dev/null | sed 's/^/  /' \
  || echo "  (request failed to complete)"

echo ""
if [[ $fail -eq 0 ]]; then
  echo "HEALTH: all services UP."
else
  echo "HEALTH: one or more services not UP (see above)." >&2
fi
exit $fail
