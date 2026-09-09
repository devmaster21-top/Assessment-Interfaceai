#!/usr/bin/env bash
set -euo pipefail

# Run the target app separately first:
# uvicorn demo_app.app:app --host 127.0.0.1 --port 8000

cuagent discover \
  --goal "Look up member 12345 and read their current savings balance" \
  --target http://127.0.0.1:8000/ \
  --param member_id=12345 \
  --artifact evidence/artifacts/lookup_member_savings.v1.json \
  --headed

cuagent replay \
  --artifact evidence/artifacts/lookup_member_savings.v1.json \
  --param member_id=67890 \
  --headed
