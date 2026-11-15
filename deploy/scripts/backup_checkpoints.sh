#!/usr/bin/env bash
# =============================================================================
# AetherOS — copy the signed ledger checkpoints to a place the database's operators cannot rewrite (KAN-51)
#
# The checkpoints (core/audit/anchor.py) prove the audit ledger was not shortened or rewritten. A copy kept next to the
# database is worth little: whoever can restore an old database can also restore an old checkpoint file. Send them to a
# separate destination: a different account/bucket with object lock, or a directory on another host (append-only).
# The restore drill (scripts/restore_drill.py --anchor-file) later checks a restored database against this copy.
#
#   CHECKPOINT_DEST=s3remote:aetheros-checkpoints bash deploy/scripts/backup_checkpoints.sh     # rclone remote
#   CHECKPOINT_DEST=/mnt/vault/aetheros-checkpoints bash deploy/scripts/backup_checkpoints.sh   # directory
#
# Reads AETHER_LEDGER_ANCHOR_FILE (default ~/.aether_os/ledger_anchors.jsonl) and AETHER_LEDGER_SIGNING_KEY. Only the PUBLIC
# key is copied; the signing key never leaves the host. Every run writes new files (UTC timestamp in the name), never
# overwrites or deletes. Exit 0 = copied and the checksum matches.
# =============================================================================
set -euo pipefail

DEST="${CHECKPOINT_DEST:?CHECKPOINT_DEST is required (rclone remote:path or a directory)}"
ANCHORS="${AETHER_LEDGER_ANCHOR_FILE:-$HOME/.aether_os/ledger_anchors.jsonl}"
KEY="${AETHER_LEDGER_SIGNING_KEY:-$HOME/.aether_os/ledger_signing_key.pem}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

[[ -s "$ANCHORS" ]] || { echo "ERROR: no checkpoints at $ANCHORS (nothing to protect yet, or wrong path)" >&2; exit 1; }
[[ -f "$KEY" ]] || { echo "ERROR: signing key $KEY not found (needed to publish the public half)" >&2; exit 1; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp "$ANCHORS" "$WORK/ledger_anchors_$STAMP.jsonl"
openssl pkey -in "$KEY" -pubout -out "$WORK/ledger_public_key_$STAMP.pem"
( cd "$WORK" && sha256sum ledger_anchors_"$STAMP".jsonl ledger_public_key_"$STAMP".pem > "SHA256SUMS_$STAMP" 2>/dev/null \
  || shasum -a 256 ledger_anchors_"$STAMP".jsonl ledger_public_key_"$STAMP".pem > "SHA256SUMS_$STAMP" )
grep -q "PRIVATE" "$WORK"/*.pem && { echo "ERROR: refusing to copy private key material" >&2; exit 1; }

if [[ "$DEST" == *:* && "$DEST" != /* ]]; then
    command -v rclone >/dev/null || { echo "ERROR: rclone is required for a remote destination" >&2; exit 1; }
    rclone copy --immutable "$WORK" "$DEST"
else
    mkdir -p "$DEST"
    for f in "$WORK"/*; do [[ -e "$DEST/$(basename "$f")" ]] && { echo "ERROR: $(basename "$f") already exists in $DEST" >&2; exit 1; }; done
    cp "$WORK"/* "$DEST"/
    ( cd "$DEST" && { sha256sum -c "SHA256SUMS_$STAMP" 2>/dev/null || shasum -a 256 -c "SHA256SUMS_$STAMP"; } >/dev/null )
fi
echo "$(date -u +%FT%TZ) checkpoints copied to $DEST as *_$STAMP ($(wc -l < "$ANCHORS") checkpoints)"
