#!/usr/bin/env bash
# End-to-end smoke test of the murmurent signed-identity lifecycle (phases 0-5),
# simulating a MAYOR, a PI, and a MEMBER on ONE machine via separate
# MURMURENT_HOME roots. Non-destructive: everything lives under a fresh temp dir.
# Requires `murmurent` on PATH.
set -euo pipefail

# Use the exact interpreter `murmurent` was installed with for the few python bits.
PY="$(head -1 "$(command -v murmurent)" | sed 's/^#!//')"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/wig-smoke.XXXXXX")"
echo "workdir: $WORK"

# `centre-init` writes ~/.murmurent/registrar via Path.home() — it ignores
# MURMURENT_HOME — so back it up and restore it on exit. Keeps the smoke test from
# clobbering your real registrar sentinel.
_SENTINEL="$HOME/.murmurent/registrar"
_SENTINEL_BAK="$(cat "$_SENTINEL" 2>/dev/null || true)"
_restore_sentinel(){
  if [ -n "$_SENTINEL_BAK" ]; then
    mkdir -p "$(dirname "$_SENTINEL")"; printf '%s\n' "$_SENTINEL_BAK" > "$_SENTINEL"
  else
    rm -f "$_SENTINEL"
  fi
}
trap _restore_sentinel EXIT

MAYOR="$WORK/mayor"; PI="$WORK/pi"; MEMBER="$WORK/member"
LABINFO="$WORK/mayor_labinfo"; LABMGMT="$WORK/mayor_labmgmt"
hr(){ echo; echo "===== $* ====="; }

mayor_env(){ export MURMURENT_HOME="$MAYOR" MURMURENT_LAB_INFO_ROOT="$LABINFO" \
             MURMURENT_LAB_MGMT_REPO="$LABMGMT" MURMURENT_USER=tbrowne5; }
pi_env(){ export MURMURENT_HOME="$PI" MURMURENT_LAB_INFO_ROOT="$WORK/pi_labinfo" \
          MURMURENT_USER=yxia266; unset MURMURENT_LAB_MGMT_REPO; }
member_env(){ export MURMURENT_HOME="$MEMBER" MURMURENT_LAB_INFO_ROOT="$WORK/mem_labinfo" \
              MURMURENT_USER=allie; unset MURMURENT_LAB_MGMT_REPO; }

# ---------------- MAYOR: bootstrap ----------------
hr "MAYOR: bootstrap centre + root CA"
mayor_env
murmurent centre-init --no-prompt --name "Smoke Centre" --institution "Test U" \
        --unique-name smoke --mayor @tbrowne5
OUT="$(murmurent centre-root-keygen)"; echo "$OUT" | sed -n '1,3p'
TRUST="$(printf '%s\n' "$OUT" | grep -oE 'ed25519:[A-Za-z0-9+/=]+' | head -1)"
echo "TRUST ROOT = $TRUST"

hr "MAYOR: register a lab for PI @yxia266 (stands in for a lab join-request)"
"$PY" -c "from murmurent.core import registrar as R; R.create_lab(name='xia_lab', display_name='Xia Lab', pi_handle='@yxia266', pi_email='y@test.edu')"

# ---------------- PI: enroll ----------------
hr "PI: mint key + enroll (proof of possession)"
pi_env
murmurent identity-init | sed -n '1,2p'
murmurent enroll --out "$WORK/pi_enroll.json"

# ---------------- MAYOR: issue PI card ----------------
hr "MAYOR: issue root-signed PI card"
mayor_env
murmurent issue-pi-card "$WORK/pi_enroll.json" --actor @tbrowne5 --out "$WORK/pi_card.json"

# ---------------- PI: import ----------------
hr "PI: import PI card (pins the trust root) + whoami"
pi_env
murmurent import-card "$WORK/pi_card.json" --trust-root "$TRUST"
murmurent whoami

# ---------------- MEMBER: enroll ----------------
hr "MEMBER: mint key + enroll"
member_env
murmurent identity-init | sed -n '1,2p'
murmurent enroll --group xia_lab --out "$WORK/mem_enroll.json"
MEMFP="$("$PY" -c 'from murmurent.core import idkeys as K; print(K.local_fingerprint())')"
echo "member fingerprint = $MEMFP"

# ---------------- PI: issue member card ----------------
hr "PI: issue member card (PI-signed, chains to root)"
pi_env
murmurent issue-member-card "$WORK/mem_enroll.json" --group xia_lab --out "$WORK/mem_bundle.json"

# ---------------- MEMBER: import ----------------
hr "MEMBER: import member card (verifies member->PI->root) + whoami"
member_env
murmurent import-card "$WORK/mem_bundle.json" --trust-root "$TRUST"
murmurent whoami
echo "-> local identity check:"
"$PY" -c "from murmurent.core import issuance as I; print(I.verify_local_identity())"

# ---------------- REVOCATION ----------------
hr "MAYOR: revoke the member (by fingerprint) + publish CRL"
mayor_env
murmurent revoke --fingerprint "$MEMFP"
murmurent crl --out "$WORK/crl.json"

hr "MEMBER: fetch the CRL -> local identity is now REJECTED"
member_env
"$PY" -c "import json; from murmurent.core import revocation as R; R.import_distributed_crl('smoke', json.load(open('$WORK/crl.json')))"
echo "-> local identity check after revocation:"
"$PY" -c "from murmurent.core import issuance as I; print(I.verify_local_identity())"

hr "DONE"
echo "clean up with: rm -rf $WORK"
