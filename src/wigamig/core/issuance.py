"""
Purpose: card ISSUANCE + import — the admin-registrar side of PI onboarding and
the PI/member side of accepting a card. Ties together:

  - ``centre_root`` (the centre CA root key),
  - ``idcert`` (signing, proof-of-possession, chain verification), and
  - ``identity_card`` (role derivation from the registry + local materialization
    of a scoped registry so the dashboard resolver works).

The bottom-up PI flow this implements:

  1. PI runs ``wigamig enroll`` → a proof-of-possession request (signed by their
     machine key, carrying their public key). They send it to the mayor.
  2. Mayor runs ``issue_pi_card`` → verifies the PoP, confirms the handle is a
     registered PI/leader, and signs a PI card with the **centre root key**.
  3. PI runs ``verify_and_import_pi_card`` → checks the card chains to the pinned
     centre root, then materializes their role locally.

Trust boundary: a card is verified against the **pinned** centre root
(``idcert.verify_or_pin_root`` / TOFU). The pin must come from the centre's
*published* signing recipient, confirmed out-of-band — never from the same
channel that delivered the card. Revocation (the fail-closed CRL) bites at
*access* time (the dashboard, Phase 5), not at import — holding a revoked card
grants nothing on its own.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import centre_init as _ci
from . import centre_root as _cr
from . import idcert as _cert
from . import identity_card as _ic
from . import idkeys as _k


class IssuanceError(RuntimeError):
    """Issuance or import of a signed card failed."""


def _home() -> Path:
    return Path(os.environ.get("WIGAMIG_HOME", str(Path.home() / ".wigamig")))


def cards_dir() -> Path:
    return _home() / "cards"


def _safe(name: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in str(name or ""))


def _git_init_lab_repo(lab_repo: Path) -> None:
    """Make the lab's management repo a real git repo so the roster is
    version-controlled (and pushable to the lab's git provider later). Best-effort
    and idempotent — a missing ``git`` or an existing repo is not an error."""
    import shutil
    import subprocess
    if (lab_repo / ".git").exists() or not shutil.which("git"):
        return
    try:
        subprocess.run(["git", "init", "-q"], cwd=str(lab_repo),  # noqa: S603,S607
                       check=False, capture_output=True, timeout=15)
        gi = lab_repo / ".gitignore"
        if not gi.is_file():
            gi.write_text(".DS_Store\n", encoding="utf-8")
    except (OSError, subprocess.SubprocessError):
        pass


# ---------------------------------------------------------------------------
# Mayor / admin-registrar side: issue a signed PI card
# ---------------------------------------------------------------------------

def issue_pi_card(handle: str, *, enrollment: dict, actor: str = "",
                  env: dict | None = None, issued_at=None,
                  ttl_days: int = _cert.DEFAULT_TTL_DAYS,
                  expected_nonce: str | None = None) -> dict:
    """Issue a centre-root-signed PI card for a registered PI/leader.

    ``enrollment`` is the PI's proof-of-possession request (from ``wigamig
    enroll``); its embedded public key is what gets bound into the card, and its
    self-signature is verified first so we only ever certify a key the PI proved
    they hold. Requires a centre, the centre root key, and ``handle`` resolving
    to a ``lab_pi`` / ``core_leader`` in the registry."""
    centre = _ci.read_centre(env=env)
    if centre is None:
        raise IssuanceError("no centre initialised; run `wigamig centre-init` first")
    if not _cr.have_root_key():
        raise IssuanceError("no centre root key; run `wigamig centre-root-keygen` first")

    pubkey = (enrollment.get("payload") or {}).get("pubkey") if isinstance(enrollment, dict) else None
    if not pubkey:
        raise IssuanceError("enrollment request has no public key")
    if not _cert.verify_enrollment(enrollment, expected_nonce=expected_nonce):
        raise IssuanceError("proof-of-possession failed (bad enrollment signature/nonce)")

    # Derive the PI's role(s) from the registry (reuses the scoped-card logic).
    try:
        scoped = _ic.build_card(handle, env=env, issued_by=actor, issued_at=issued_at)
    except ValueError as exc:
        raise IssuanceError(str(exc)) from exc
    kinds = {r.get("kind") for r in scoped["roles"]}
    if not (kinds & {"lab_pi", "core_leader"}):
        raise IssuanceError(
            f"@{scoped['netname']} is not a PI or core leader in this centre "
            "(a PI card is only for lab PIs / core leaders)")

    root = _cr.load_root_private()
    centre_name = centre.unique_name or centre.install_id
    card = _cert.issue_pi_card(
        handle=scoped["netname"], pi_pubkey=pubkey, centre=centre_name,
        root_priv=root, issuer_handle=actor or centre.founding_mayor,
        roles=scoped["roles"], issued_at=issued_at, ttl_days=ttl_days)
    _record_issued(centre_name, card, "pi")
    return card


# ---------------------------------------------------------------------------
# Standalone PI: self-issue your own PI ID (no mayor / centre needed)
# ---------------------------------------------------------------------------

def self_issue_pi_card(handle: str, group: str, *, group_kind: str = "lab",
                       env: dict | None = None, issued_at=None,
                       ttl_days: int = _cert.DEFAULT_TTL_DAYS) -> dict:
    """A PI self-issues their own **PI ID**: a PI card signed by their OWN key,
    making them the root (certificate authority) of their own lab/core. No mayor
    or centre is required — you can immediately issue member cards, and members
    pin your key as their trust anchor.

    Your key is the constant: if the lab later joins a centre, the mayor issues a
    SEPARATE centre-signed PI card attesting this same key, and your members'
    cards keep verifying (only the trust anchor changes). Returns
    ``{pi_card, trust_root, realm}`` — hand ``trust_root`` to members so they can
    ``import-card --trust-root <it>``.
    """
    if not _k.have_keys():
        raise IssuanceError("no local keypair; run `wigamig identity-init` first")
    if not group.strip():
        raise IssuanceError("a lab/core name is required to self-issue your PI ID")
    priv = _k.load_private()
    pub = priv.public_key()
    pub_str = _k.encode_public(pub)
    at = "@" + str(handle).lstrip("@").strip().lower()
    # The lab's own trust realm (analogue of a centre's unique_name), namespaced
    # by handle so two standalone labs can't collide locally.
    realm = _safe(f"{at.lstrip('@')}-{group}")
    kind = "core_leader" if group_kind == "core" else "lab_pi"
    roles = [{"kind": kind, "group": group, "pi": at}]
    # Self-signed: issuer key == subject key == this PI's key.
    card = _cert.issue_pi_card(handle=at, pi_pubkey=pub, centre=realm,
                               root_priv=priv, issuer_handle=at, roles=roles,
                               issued_at=issued_at, ttl_days=ttl_days)
    # Pin our own key as the anchor for our realm; materialize our identity card
    # so issue_member_card + the dashboard resolve us as this group's PI.
    _cert.pin_root(realm, pub_str)
    _ic.import_card(_scoped_from_signed(card["payload"]), env=env)
    d = cards_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{_safe(realm)}_pi.json").write_text(_cert.dumps(card), encoding="utf-8")
    _record_issued(realm, card, "pi")

    # Establish the lab's own management repo (the roster's home) and pin it, then
    # write the PI's own record — the roster is the single source of truth.
    from . import membership as _mem
    from . import repo as _repo
    lab_repo = _repo.lab_repo_path(group)
    (lab_repo / "members").mkdir(parents=True, exist_ok=True)
    lab_md = lab_repo / "lab.md"
    if not lab_md.is_file():
        lab_md.write_text(f"---\nlab: {group}\npi: '{at}'\nkind: {group_kind}\n---\n\n"
                          f"# {group}\n", encoding="utf-8")
    _git_init_lab_repo(lab_repo)          # version-control the roster (best-effort)
    _repo.set_lab_mgmt_path(lab_repo)
    prof = _read_profile(env)
    _mem.upsert_member(at, role="pi", email=str(prof.get("email") or ""),
                       github=str(prof.get("github") or ""),
                       card_fingerprint=card["payload"]["subject"]["fingerprint"],
                       card_id=card["payload"]["card_id"])
    return {"pi_card": card, "trust_root": pub_str, "realm": realm,
            "lab_repo": str(lab_repo)}


# ---------------------------------------------------------------------------
# PI side: enroll (prove key possession) + verify-and-import
# ---------------------------------------------------------------------------

def _read_profile(env: dict | None = None) -> dict:
    """The member's ``~/.wigamig/profile.yaml`` (from ``wigamig init``), or {}."""
    import yaml
    p = _home() / "profile.yaml"
    if not p.is_file():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def make_enrollment(handle: str, *, nonce: str | None = None,
                    group: str = "", env: dict | None = None) -> dict:
    """Build this machine's proof-of-possession enrollment request. Requires a
    local keypair (``wigamig identity-init`` / first-run auto-mint). Carries the
    member's email + github (from their ``wigamig init`` profile) so the PI can
    record them on the roster in one round trip."""
    if not _k.have_keys():
        raise IssuanceError("no local keypair; run `wigamig identity-init` first")
    centre = _ci.read_centre(env=env)
    centre_name = (centre.unique_name or centre.install_id) if centre else ""
    prof = _read_profile(env)
    priv = _k.load_private()
    return _cert.make_enrollment_request(
        handle, priv=priv, nonce=nonce or os.urandom(8).hex(),
        centre=centre_name, group=group,
        email=str(prof.get("email") or ""), github=str(prof.get("github") or ""))


def _scoped_from_signed(payload: dict) -> dict:
    """Rebuild the (unsigned) scoped-card shape ``identity_card.import_card``
    expects from an *authenticated* signed-card payload."""
    return {
        "version": _ic.CARD_VERSION,
        "netname": str(payload["subject"]["handle"]).lstrip("@"),
        "centre": payload.get("centre", ""),
        "roles": payload.get("roles", []),
        "issued_by": (payload.get("issuer") or {}).get("handle", ""),
        "issued_at": payload.get("issued_at", ""),
    }


def verify_and_import_pi_card(card, *, trust_root: str | None = None,
                              env: dict | None = None, now=None,
                              require_crl: bool = False, crl=None) -> tuple:
    """PI side: verify a signed PI card is authentic + for this centre, then
    materialize the role locally so the dashboard resolves it. Returns
    ``(Verdict, actions)``.

    ``trust_root`` (the centre's published ``ed25519:`` signing recipient) is
    pinned on first import (TOFU) — a later mismatch fails closed. Import checks
    authenticity (signature + chain + expiry + pin), not revocation; the
    fail-closed CRL check runs at access time."""
    card = _cert.loads(card) if isinstance(card, str) else card
    payload = card.get("payload") or {}
    centre_name = payload.get("centre") or ""
    if payload.get("kind") != "pi":
        raise IssuanceError("verify_and_import_pi_card: not a PI card")

    if trust_root:
        ok, reason = _cert.verify_or_pin_root(centre_name, trust_root)
        if not ok:
            raise IssuanceError(f"trust anchor: {reason}")
    pinned = _cert.load_pinned_root(centre_name)
    if pinned is None:
        raise IssuanceError(
            f"no pinned trust anchor for centre '{centre_name}'. Pass --trust-root "
            "with the centre's published signing recipient (confirm its "
            "fingerprint out-of-band first).")

    v = _cert.verify_pi_card(card, root_pub=pinned, now=now, crl=crl,
                             centre=centre_name, require_crl=require_crl)
    if not v.ok:
        raise IssuanceError(f"card rejected: {v.reason}")

    actions = _ic.import_card(_scoped_from_signed(payload), env=env)
    # Keep the signed card too — the crypto proof for later access-time checks.
    d = cards_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{_safe(centre_name)}_pi.json").write_text(_cert.dumps(card), encoding="utf-8")
    actions.append(f"stored signed PI card ({cards_dir()})")
    return v, actions


# ---------------------------------------------------------------------------
# Group-registrar (PI) side: issue a member card signed with the PI's own key
# ---------------------------------------------------------------------------

def issue_member_card(handle: str, *, enrollment: dict, group: str,
                      env: dict | None = None, issued_at=None,
                      ttl_days: int = _cert.DEFAULT_TTL_DAYS,
                      expected_nonce: str | None = None) -> dict:
    """PI/group-registrar side: sign a member card for ``handle`` in ``group``
    with the PI's OWN machine key, chaining to the centre root via the PI's card.

    Runs on the PI's machine: it uses the PI's local identity card to confirm
    they lead ``group``, verifies the member's proof-of-possession, then returns
    a **bundle** ``{"member_card", "pi_card"}`` so the member receives the whole
    chain (member → PI → root) needed to verify."""
    if not _k.have_keys():
        raise IssuanceError("no local keypair; you need your own key to sign member cards")
    local = _ic.local_card(env=env)
    if not local:
        raise IssuanceError("no identity card on this machine; import your PI card first")
    centre_name = local.get("centre") or ""
    led = {r.get("group"): r.get("kind") for r in local.get("roles", [])
           if r.get("kind") in ("lab_pi", "core_leader")}
    if group not in led:
        raise IssuanceError(
            f"you do not lead group '{group}' — cannot issue its member cards")
    group_kind = "core" if led[group] == "core_leader" else "lab"

    pi_card_path = cards_dir() / f"{_safe(centre_name)}_pi.json"
    if not pi_card_path.is_file():
        raise IssuanceError(
            "your signed PI card is missing (needed to chain member cards to the "
            "root); re-import it with `wigamig import-card`")
    pi_card = _cert.loads(pi_card_path.read_text(encoding="utf-8"))

    pubkey = (enrollment.get("payload") or {}).get("pubkey") if isinstance(enrollment, dict) else None
    if not pubkey:
        raise IssuanceError("enrollment request has no public key")
    if not _cert.verify_enrollment(enrollment, expected_nonce=expected_nonce):
        raise IssuanceError("proof-of-possession failed (bad enrollment signature/nonce)")

    pi_handle = str(local.get("netname") or "").lstrip("@")
    roles = [{"kind": "member", "group": group, "pi": f"@{pi_handle}",
              "group_kind": group_kind}]
    member_card = _cert.issue_member_card(
        handle=handle, member_pubkey=pubkey, group=group, centre=centre_name,
        pi_priv=_k.load_private(), pi_handle=pi_handle, roles=roles,
        issued_at=issued_at, ttl_days=ttl_days)
    _record_issued(centre_name, member_card, "member")
    # Roster is the source of truth: record the member with the email + github
    # they carried in their enrollment and the card's fingerprint/id.
    from . import membership as _mem
    ep = enrollment.get("payload") or {}
    _mem.upsert_member(handle, role="staff", email=str(ep.get("email") or ""),
                       github=str(ep.get("github") or ""),
                       card_fingerprint=member_card["payload"]["subject"]["fingerprint"],
                       card_id=member_card["payload"]["card_id"])
    return {"member_card": member_card, "pi_card": pi_card}


# ---------------------------------------------------------------------------
# PROJECT-scoped cards — bind a member's key to a project within a lab
# (group == "<lab>/<project>"). Structurally a member card (member → PI → root),
# so existing verifiers accept it; only the group shape + role differ. Recorded
# in a per-project ledger so the whole project can be revoked at once.
# ---------------------------------------------------------------------------

def _norm_project(project: str) -> str:
    return _safe(str(project or "").strip())


def project_group(lab: str, project: str) -> str:
    """Composite group string for a project-scoped card: ``<lab>/<project>``."""
    return f"{str(lab or '').strip()}/{_norm_project(project)}"


def _leader_groups(env: dict | None = None) -> tuple[str, dict]:
    """This machine's local card centre + ``{group: kind}`` for the groups it
    leads (lab_pi / core_leader). Raises if there is no local card."""
    local = _ic.local_card(env=env)
    if not local:
        raise IssuanceError("no identity card on this machine; import your PI card first")
    led = {r.get("group"): r.get("kind") for r in local.get("roles", [])
           if r.get("kind") in ("lab_pi", "core_leader")}
    return (local.get("centre") or ""), led


def _resolve_project_lab(led: dict, project: str, lab: str | None) -> str:
    """Pick which lab owns ``project``: the given ``lab`` (must be one we lead), or
    the sole led group, else demand disambiguation."""
    labs = list(led)
    if lab:
        if lab not in led:
            raise IssuanceError(f"you do not lead '{lab}' — cannot issue its project cards")
        return lab
    if len(labs) == 1:
        return labs[0]
    if not labs:
        raise IssuanceError("you lead no lab/core — cannot issue project cards")
    raise IssuanceError(
        f"you lead multiple groups {labs}; pass a lab to say which one owns "
        f"project '{project}'")


def project_context(project: str, *, lab: str | None = None,
                    env: dict | None = None) -> tuple[str, str]:
    """Resolve ``(centre, group)`` for a project the caller leads, where
    ``centre`` is the local trust realm and ``group`` is ``<lab>/<project>``.
    Used by both issuance and revocation so they agree on the ledger key."""
    centre_name, led = _leader_groups(env)
    lab = _resolve_project_lab(led, project, lab)
    proj = _norm_project(project)
    if not proj:
        raise IssuanceError("project name is required")
    return centre_name, project_group(lab, proj)


def issue_project_card(handle: str, *, enrollment: dict, project: str,
                       lab: str | None = None, env: dict | None = None,
                       issued_at=None, ttl_days: int = _cert.DEFAULT_TTL_DAYS,
                       expected_nonce: str | None = None) -> dict:
    """PI side: issue a PROJECT-scoped card binding ``handle``'s key to a project
    within a lab the caller leads. Verifies proof-of-possession, then signs a card
    whose ``group`` is the composite ``<lab>/<project>`` and whose role is
    ``project_member``. Chains member → PI → root exactly like a lab member card.
    Recorded in a per-project ledger (NOT the handle-keyed one) so a project card
    never clobbers the member's lab card and the project can be revoked wholesale."""
    if not _k.have_keys():
        raise IssuanceError("no local keypair; you need your own key to sign project cards")
    centre_name, led = _leader_groups(env)
    lab = _resolve_project_lab(led, project, lab)
    proj = _norm_project(project)
    if not proj:
        raise IssuanceError("project name is required")
    group = project_group(lab, proj)

    pi_card_path = cards_dir() / f"{_safe(centre_name)}_pi.json"
    if not pi_card_path.is_file():
        raise IssuanceError(
            "your signed PI card is missing (needed to chain project cards to the "
            "root); re-import it with `wigamig import-card`")
    pi_card = _cert.loads(pi_card_path.read_text(encoding="utf-8"))

    pubkey = (enrollment.get("payload") or {}).get("pubkey") if isinstance(enrollment, dict) else None
    if not pubkey:
        raise IssuanceError("enrollment request has no public key")
    if not _cert.verify_enrollment(enrollment, expected_nonce=expected_nonce):
        raise IssuanceError("proof-of-possession failed (bad enrollment signature/nonce)")

    local = _ic.local_card(env=env) or {}
    pi_handle = str(local.get("netname") or "").lstrip("@")
    roles = [{"kind": "project_member", "group": group, "lab": lab,
              "project": proj, "pi": f"@{pi_handle}"}]
    card = _cert.issue_member_card(
        handle=handle, member_pubkey=pubkey, group=group, centre=centre_name,
        pi_priv=_k.load_private(), pi_handle=pi_handle, roles=roles,
        issued_at=issued_at, ttl_days=ttl_days)
    _record_project_issued(centre_name, group, card)
    return {"member_card": card, "pi_card": pi_card, "group": group,
            "lab": lab, "project": proj}


def _record_project_issued(centre_name: str, group: str, card: dict) -> None:
    """Best-effort: index a project card in the per-project revocation ledger."""
    try:
        from . import revocation as _rev
        p = card["payload"]
        _rev.record_project_issued(centre_name, group,
                                   handle=p["subject"]["handle"],
                                   card_id=p["card_id"],
                                   fingerprint=p["subject"]["fingerprint"])
    except Exception:  # noqa: BLE001
        pass


def verify_and_import_member_card(bundle, *, trust_root: str | None = None,
                                  env: dict | None = None, now=None,
                                  require_crl: bool = False, crl=None) -> tuple:
    """Member side: verify a member card chains member → PI → the pinned centre
    root, then materialize the role locally. ``bundle`` is
    ``{"member_card", "pi_card"}`` (dict or its JSON)."""
    if isinstance(bundle, str):
        bundle = json.loads(bundle)
    member_card = bundle.get("member_card") if isinstance(bundle, dict) else None
    pi_card = bundle.get("pi_card") if isinstance(bundle, dict) else None
    if not (isinstance(member_card, dict) and isinstance(pi_card, dict)):
        raise IssuanceError("not a member-card bundle (need member_card + pi_card)")
    centre_name = (member_card.get("payload") or {}).get("centre") or ""

    if trust_root:
        ok, reason = _cert.verify_or_pin_root(centre_name, trust_root)
        if not ok:
            raise IssuanceError(f"trust anchor: {reason}")
    pinned = _cert.load_pinned_root(centre_name)
    if pinned is None:
        raise IssuanceError(
            f"no pinned trust anchor for centre '{centre_name}'. Pass --trust-root "
            "with the centre's published signing recipient (fingerprint confirmed "
            "out-of-band).")

    v = _cert.verify_member_card(member_card, pi_card, root_pub=pinned, now=now,
                                 crl=crl, centre=centre_name, require_crl=require_crl)
    if not v.ok:
        raise IssuanceError(f"card rejected: {v.reason}")

    actions = _ic.import_card(_scoped_from_signed(member_card["payload"]), env=env)
    d = cards_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{_safe(centre_name)}_member.json").write_text(
        json.dumps(bundle, indent=2), encoding="utf-8")
    actions.append(f"stored signed member-card bundle ({cards_dir()})")
    return v, actions


# ---------------------------------------------------------------------------
# Issuance ledger + local card verification (used by the dashboard gate)
# ---------------------------------------------------------------------------

def _record_issued(centre_name: str, card: dict, kind: str) -> None:
    """Best-effort: record an issued card so a later removal can revoke it by
    handle. Never break issuance if the ledger write fails."""
    try:
        from . import revocation as _rev
        p = card["payload"]
        _rev.record_issued(centre_name, handle=p["subject"]["handle"],
                           card_id=p["card_id"],
                           fingerprint=p["subject"]["fingerprint"], kind=kind)
    except Exception:  # noqa: BLE001
        pass


def verify_local_identity(*, env: dict | None = None, now=None) -> tuple[str, str]:
    """Verify THIS machine's stored signed card still holds. Returns
    ``(status, reason)`` where status is ``"no_card"`` (nothing to check — fall
    through to registry authz), ``"ok"``, or ``"reject"``.

    Checks the chain to the pinned root + expiry + tamper, and revocation when a
    CRL is available (fresh-signed on the mayor's machine, or a distributed CRL on
    a member's). A member with no distributed CRL still gets expiry/tamper
    enforcement — remote revocation there arrives with CRL distribution."""
    local = _ic.local_card(env=env)
    if not local:
        return ("no_card", "")
    centre = local.get("centre") or ""
    pinned = _cert.load_pinned_root(centre)
    if pinned is None:
        return ("ok", "")  # no anchor → can't crypto-verify; registry authz applies
    from . import revocation as _rev
    crl = _rev.current_crl(centre)
    require = crl is not None

    member_p = cards_dir() / f"{_safe(centre)}_member.json"
    pi_p = cards_dir() / f"{_safe(centre)}_pi.json"
    if member_p.is_file():
        b = json.loads(member_p.read_text(encoding="utf-8"))
        v = _cert.verify_member_card(b.get("member_card"), b.get("pi_card"),
                                     root_pub=pinned, now=now, crl=crl,
                                     centre=centre, require_crl=require)
    elif pi_p.is_file():
        v = _cert.verify_pi_card(_cert.loads(pi_p.read_text(encoding="utf-8")),
                                 root_pub=pinned, now=now, crl=crl, centre=centre,
                                 require_crl=require)
    else:
        return ("no_card", "")
    return ("ok", "") if v.ok else ("reject", v.reason)


__all__ = [
    "IssuanceError", "issue_pi_card", "self_issue_pi_card", "make_enrollment",
    "verify_and_import_pi_card", "issue_member_card",
    "verify_and_import_member_card", "verify_local_identity", "cards_dir",
]
