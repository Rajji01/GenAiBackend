"""
CLI utility — mint a new API key for /chat/* access.

Prints the raw key ONCE (to stdout, at creation). Stores only the
SHA-256 hash in `api_keys`. The user is expected to copy the raw key
into their client's `X-API-Key` header immediately; it cannot be
recovered later, from anywhere.

Usage (from repo root, with the venv active):

    python narration-enrichment/scripts/create_api_key.py --label rajat-laptop

Not an HTTP endpoint by design. Bootstrapping key creation via HTTP
is a common early foothold; keeping key issuance out of the API
surface entirely in P3 is the simplest defense. A proper
provisioning flow arrives in P7 (Secrets Manager, multi-user).
"""

from __future__ import annotations

import argparse
import sys

# Local imports are done inside main() to keep --help fast and to
# defer any DB engine construction until the script actually runs.


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mint a new API key for /chat/* access. Prints the raw key ONCE.",
    )
    parser.add_argument(
        "--label",
        required=True,
        help="Human-readable label so audit queries can identify the key later (e.g. 'rajat-laptop').",
    )
    args = parser.parse_args()

    from narration_enrichment import auth
    from narration_enrichment.db import SessionLocal, insert_api_key

    raw = auth.generate_raw_key()
    key_hash = auth.hash_key(raw)

    db = SessionLocal()
    try:
        row = insert_api_key(db, key_hash=key_hash, label=args.label)
    finally:
        db.close()

    # Print raw key to stdout ONCE. Keep it visually distinct so a
    # user piping this into another command notices what they're
    # capturing. The hash + label go to stderr so a shell like
    # `KEY=$(python create_api_key.py --label x)` captures only the
    # raw key.
    print(raw)
    sys.stderr.write(
        f"api_key_created label={row.label!r} key_hash_prefix={row.key_hash[:12]}...\n"
        "Store this raw key now — it CANNOT be recovered later.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
