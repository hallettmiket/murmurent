"""
Purpose: keyring (Phase 1 MVP) — distribute a centre's shared secrets across all
of one principal's machines. Each machine holds its OWN age identity (private key
never leaves it); each secret is one age file ("box") in the lab_info git repo,
locked to every authorised machine whose ROLE is a listed consumer. A machine
opens exactly the boxes locked to include its key — so a `server`-role machine
can hold every file yet be unable to open a `mayor`-only box.

Author: Mike Hallett (with Claude Code)
Date: 2026-07-28

Layout (inside the lab_info repo):

    .keyring/
      recipients.yaml   # roster: one public key + role per machine
      manifest.yaml     # declarative: each secret's target path, mode, consumers
      secrets/<name>.age # one encrypted box per secret

Phases 1-2: identity, authorize, set-secret, sync, status, check, rotate-secret,
revoke. The reconcile-loop auto-sync and signed commits remain later phases.
See the design doc / spec.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from . import age_crypto
from .registrar import lab_info_root

KEYRING_DIRNAME = ".keyring"
RECIPIENTS_FILE = "recipients.yaml"
MANIFEST_FILE = "manifest.yaml"
SECRETS_DIRNAME = "secrets"
IDENTITY_REL = ("keyring", "identity.age.key")   # under MURMURENT_HOME (per-machine)

#: Roles a machine can hold. ``mayor`` gets everything incl. crown-jewel secrets;
#: ``server`` gets only what its consumer lists include. Extensible in later phases.
VALID_ROLES = ("mayor", "server")


class KeyringError(RuntimeError):
    """A keyring operation failed (no identity, not entitled, bad manifest, …)."""


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def _home() -> Path:
    return Path(os.environ.get("MURMURENT_HOME") or (Path.home() / ".murmurent"))


def identity_path() -> Path:
    """This machine's private age identity (per-machine, never synced, 0600)."""
    return _home().joinpath(*IDENTITY_REL)


def keyring_dir(env: dict[str, str] | None = None) -> Path:
    return lab_info_root(env) / KEYRING_DIRNAME


def secrets_dir(env: dict[str, str] | None = None) -> Path:
    return keyring_dir(env) / SECRETS_DIRNAME


def secret_box_path(name: str, env: dict[str, str] | None = None) -> Path:
    return secrets_dir(env) / f"{name}.age"


# --------------------------------------------------------------------------- #
# This machine's identity
# --------------------------------------------------------------------------- #
def has_identity() -> bool:
    return identity_path().is_file()


def identity_recipient() -> str:
    """The public recipient (``age1…``) of this machine's identity."""
    p = identity_path()
    if not p.is_file():
        raise KeyringError("no keyring identity on this machine; run "
                           "`murmurent keyring init` first.")
    m = re.search(r"(age1[0-9a-z]+)", p.read_text(encoding="utf-8"))
    if not m:
        raise KeyringError(f"could not read a public recipient from {p}")
    return m.group(1)


def ensure_identity() -> str:
    """Create this machine's identity if it is missing; return its public
    recipient either way. Idempotent."""
    if has_identity():
        return identity_recipient()
    if not age_crypto.age_available():
        raise KeyringError("age is not installed; install it from "
                           "https://age-encryption.org, then re-run.")
    return age_crypto.keygen(identity_path())   # writes 0600, returns recipient


# --------------------------------------------------------------------------- #
# Roster + manifest I/O
# --------------------------------------------------------------------------- #
def _load_yaml_map(path: Path, kind: str) -> dict:
    """Parse a ``.keyring`` YAML file into a dict, turning a malformed/half-written
    file into a clear ``KeyringError`` instead of a raw YAML traceback."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        raise KeyringError(f"malformed {kind} at {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise KeyringError(f"malformed {kind} at {path}: expected a mapping")
    return data


def load_recipients(env: dict[str, str] | None = None) -> dict:
    p = keyring_dir(env) / RECIPIENTS_FILE
    if not p.is_file():
        return {"version": 1, "machines": []}
    data = _load_yaml_map(p, ".keyring/recipients.yaml")
    data.setdefault("version", 1)
    data.setdefault("machines", [])
    if not isinstance(data["machines"], list):
        raise KeyringError(f"malformed {p}: 'machines' must be a list")
    return data


def save_recipients(data: dict, env: dict[str, str] | None = None) -> Path:
    d = keyring_dir(env)
    d.mkdir(parents=True, exist_ok=True)
    p = d / RECIPIENTS_FILE
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return p


def load_manifest(env: dict[str, str] | None = None) -> dict:
    p = keyring_dir(env) / MANIFEST_FILE
    if not p.is_file():
        return {"version": 1, "secrets": []}
    data = _load_yaml_map(p, ".keyring/manifest.yaml")
    data.setdefault("version", 1)
    data.setdefault("secrets", [])
    if not isinstance(data["secrets"], list):
        raise KeyringError(f"malformed {p}: 'secrets' must be a list")
    return data


def save_manifest(data: dict, env: dict[str, str] | None = None) -> Path:
    d = keyring_dir(env)
    d.mkdir(parents=True, exist_ok=True)
    p = d / MANIFEST_FILE
    p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #
def this_machine(env: dict[str, str] | None = None) -> dict | None:
    """This machine's roster entry (matched by its identity's recipient), or
    ``None`` if it has no identity or is not yet authorised."""
    if not has_identity():
        return None
    rec = identity_recipient()
    for m in load_recipients(env).get("machines", []):
        if m.get("recipient") == rec:
            return m
    return None


def _secret_by_name(name: str, env: dict[str, str] | None = None) -> dict | None:
    for s in load_manifest(env).get("secrets", []):
        if s.get("name") == name:
            return s
    return None


def recipients_for(secret: dict, env: dict[str, str] | None = None) -> list[str]:
    """Public keys of every roster machine whose role is in ``secret``'s
    ``consumers`` — i.e. exactly the machines that get a slot in this box."""
    consumers = set(secret.get("consumers") or [])
    out: list[str] = []
    for m in load_recipients(env).get("machines", []):
        if m.get("role") in consumers and m.get("recipient"):
            out.append(m["recipient"])
    return out


# --------------------------------------------------------------------------- #
# Lock / unlock
# --------------------------------------------------------------------------- #
def lock_secret(name: str, plaintext: str, env: dict[str, str] | None = None,
                *, secret: dict | None = None) -> Path:
    """Encrypt ``plaintext`` to every recipient entitled to ``name`` and write
    the box. Overwrites an existing box (re-lock). ``secret`` lets the caller pass
    the entry directly (used by ``set_secret`` to lock BEFORE the manifest is
    saved, so a failure leaves no dangling entry)."""
    s = secret if secret is not None else _secret_by_name(name, env)
    if s is None:
        raise KeyringError(f"no secret '{name}' in the manifest")
    recs = recipients_for(s, env)
    if not recs:
        raise KeyringError(
            f"secret '{name}' has no recipients yet — no authorised machine has "
            f"a role in {s.get('consumers')!r}. Authorise a machine first.")
    ciphertext = age_crypto.encrypt_multi(recs, plaintext)
    sd = secrets_dir(env)
    sd.mkdir(parents=True, exist_ok=True)
    box = secret_box_path(name, env)
    box.write_text(ciphertext, encoding="utf-8")
    return box


def unlock_secret(name: str, env: dict[str, str] | None = None) -> str:
    """Decrypt ``name``'s box with THIS machine's identity. Raises
    ``KeyringError`` if the box is missing or this machine has no slot in it."""
    box = secret_box_path(name, env)
    if not box.is_file():
        raise KeyringError(f"no box on disk for secret '{name}'")
    if not has_identity():
        raise KeyringError("no keyring identity on this machine; run "
                           "`murmurent keyring init` first.")
    try:
        return age_crypto.decrypt(box.read_text(encoding="utf-8"),
                                  key_path=identity_path())
    except age_crypto.AgeError as exc:
        raise KeyringError(
            f"this machine cannot open '{name}' — it is not a recipient of that "
            f"box.") from exc


# --------------------------------------------------------------------------- #
# Operations
# --------------------------------------------------------------------------- #
def set_secret(name: str, plaintext: str, *, target: str, mode: str = "0600",
               consumers: list[str], env: dict[str, str] | None = None) -> Path:
    """Add/update a secret in the manifest, then lock it. ``consumers`` are
    roles (e.g. ``["mayor", "server"]``)."""
    bad = [r for r in consumers if r not in VALID_ROLES]
    if bad:
        raise KeyringError(f"unknown role(s) {bad}; one of {list(VALID_ROLES)}")
    try:
        int(str(mode), 8)                          # fail fast on a bad mode
    except ValueError:
        raise KeyringError(f"invalid mode {mode!r}; expected octal like '0600'") from None
    entry = {"name": name, "target": _portable_target(target), "mode": mode,
             "consumers": list(consumers)}
    # Lock FIRST (encrypt + write the box), using the entry directly, so a failure
    # (no recipients, age error) never leaves a manifest entry without a box.
    box = lock_secret(name, plaintext, env, secret=entry)
    man = load_manifest(env)
    secrets = man["secrets"]
    for i, existing in enumerate(secrets):        # replace in place → smaller git diffs
        if existing.get("name") == name:
            secrets[i] = entry
            break
    else:
        secrets.append(entry)
    save_manifest(man, env)
    return box


def _relock_role_boxes(role: str, env: dict[str, str] | None = None
                       ) -> tuple[list[str], list[str], list[str]]:
    """Re-lock every box whose consumers include ``role`` to match the CURRENT
    roster — so a just-added recipient gains a slot and a just-removed one loses
    it. Uses this machine's key to read each box. Returns
    ``(affected, relocked, skipped)``: ``affected`` is every box the role can
    read; ``skipped`` are those this machine could not re-lock (not a recipient,
    or the box would drop to zero recipients)."""
    affected: list[str] = []
    relocked: list[str] = []
    skipped: list[str] = []
    for s in load_manifest(env)["secrets"]:
        if role not in (s.get("consumers") or []):
            continue
        affected.append(s["name"])
        try:
            plaintext = unlock_secret(s["name"], env)
            lock_secret(s["name"], plaintext, env)
            relocked.append(s["name"])
        except KeyringError:
            skipped.append(s["name"])
    return affected, relocked, skipped


def authorize(recipient: str, label: str, role: str,
              env: dict[str, str] | None = None) -> dict:
    """Add a machine's public key to the roster and re-lock every secret whose
    consumers include ``role`` so the newcomer gets a slot. Re-locking requires
    the plaintext, so a secret this machine cannot itself open is skipped and
    reported (a machine can only extend access to boxes it can already read)."""
    if role not in VALID_ROLES:
        raise KeyringError(f"unknown role {role!r}; one of {list(VALID_ROLES)}")
    if not (recipient or "").startswith("age1"):
        raise KeyringError(f"not a valid age recipient: {recipient!r}")

    rec = load_recipients(env)
    machines = [m for m in rec["machines"]
                if m.get("recipient") != recipient and m.get("label") != label]
    machines.append({"label": label, "recipient": recipient, "role": role,
                     "added": str(date.today())})
    rec["machines"] = machines
    save_recipients(rec, env)

    _, relocked, skipped = _relock_role_boxes(role, env)
    return {"label": label, "role": role, "relocked": relocked, "skipped": skipped}


def rotate_secret(name: str, new_plaintext: str,
                  env: dict[str, str] | None = None) -> Path:
    """Replace an EXISTING secret's value and re-lock its box (same target, mode,
    and consumers). Use this after regenerating the real secret (e.g. a new Slack
    token) — it does not invent a value. Raises if the secret is not in the
    manifest (use :func:`set_secret` to add a new one)."""
    if _secret_by_name(name, env) is None:
        raise KeyringError(f"no secret '{name}' to rotate; add it with set-secret")
    return lock_secret(name, new_plaintext, env)


def revoke(label: str, env: dict[str, str] | None = None) -> dict:
    """Remove a machine from the roster and re-lock every box it could open so it
    no longer gets a slot going forward.

    IMPORTANT: this stops *future* access only. Because git history is permanent,
    the removed machine can still decrypt the OLD box from history — so every
    secret it could read MUST have its value rotated to fully neutralise it. Those
    secrets are returned under ``must_rotate`` for the operator to rotate (with
    freshly-generated values) via :func:`rotate_secret`."""
    rec = load_recipients(env)
    victim = next((m for m in rec["machines"] if m.get("label") == label), None)
    if victim is None:
        raise KeyringError(f"no machine labelled {label!r} in the roster")
    role = victim.get("role")
    rec["machines"] = [m for m in rec["machines"] if m.get("label") != label]
    save_recipients(rec, env)

    # re-lock (now excludes the victim); every affected box must ALSO have its
    # value rotated, since git history still holds the old box the victim can read
    must_rotate, relocked, skipped = _relock_role_boxes(role, env)
    return {"label": label, "role": role, "relocked": relocked,
            "skipped": skipped, "must_rotate": must_rotate}


def _expand(target: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(target)))


def _portable_target(target: str) -> str:
    """Store secret targets ``~``-relative when they live under the current home,
    so the manifest is portable to a machine with a different username. A shell
    usually expands ``~`` before murmurent sees it (``--target ~/.config/x``
    arrives as ``/Users/qa/.config/x``); this re-tildes it so a peer whose home
    is ``/Users/bob`` unpacks under ITS own home. Paths genuinely outside home
    (e.g. ``/var/lib/...``) are kept absolute — those are machine-specific on
    purpose."""
    p = Path(os.path.expanduser(os.path.expandvars(target)))
    try:
        return str(Path("~") / p.relative_to(Path.home()))
    except ValueError:
        return str(p)


def _write_private(path: Path, text: str, mode: int) -> None:
    """Write ``text`` to ``path`` atomically, at ``mode``, with no window where a
    secret is world-readable or half-written: create a temp file in the same
    directory (so ``rename`` is atomic), ``fchmod`` it to ``mode`` *before*
    writing, then ``os.replace`` over the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".kr-tmp-")
    fd_owned = True                      # we still own fd until fdopen takes it
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fd_owned = False             # the context manager now closes fd
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        if fd_owned:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass
class SyncItem:
    name: str
    target: str
    action: str          # write | would-write | unchanged | skip-not-entitled | error
    detail: str = ""


def sync(env: dict[str, str] | None = None, *, apply: bool = False) -> list[SyncItem]:
    """Decrypt every secret this machine is entitled to and write it to its
    target path (mode from the manifest). Dry-run unless ``apply``. Existing
    targets are backed up to ``<target>.bak`` before overwrite — never a silent
    clobber. Does NOT pull; the command layer pulls first."""
    me = this_machine(env)
    if me is None:
        raise KeyringError(
            "this machine is not authorised yet. Run `murmurent keyring init`, "
            "share the printed recipient, and have an existing machine run "
            "`murmurent keyring authorize`.")
    my_role = me.get("role")
    items: list[SyncItem] = []
    for s in load_manifest(env)["secrets"]:
        name = s["name"]
        target = _expand(s["target"])
        if my_role not in (s.get("consumers") or []):
            items.append(SyncItem(name, str(target), "skip-not-entitled"))
            continue
        try:
            plaintext = unlock_secret(name, env)
        except KeyringError as exc:
            items.append(SyncItem(name, str(target), "error", str(exc)))
            continue
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        try:
            want_mode = int(str(s.get("mode", "0600")), 8)
        except ValueError:
            items.append(SyncItem(name, str(target), "error",
                                  f"invalid mode {s.get('mode')!r} in manifest"))
            continue
        if current == plaintext:
            # content already correct — repair a drifted file mode if needed
            if target.is_file() and stat.S_IMODE(target.stat().st_mode) != want_mode:
                if apply:
                    os.chmod(target, want_mode)
                    items.append(SyncItem(name, str(target), "mode-fixed", f"0{want_mode:o}"))
                else:
                    items.append(SyncItem(name, str(target), "would-fix-mode", f"0{want_mode:o}"))
            else:
                items.append(SyncItem(name, str(target), "unchanged"))
            continue
        if not apply:
            items.append(SyncItem(name, str(target), "would-write"))
            continue
        # back up the prior value (also 0600 — it is a secret) before overwrite
        if target.is_file():
            _write_private(Path(str(target) + ".bak"), current or "", 0o600)
        _write_private(target, plaintext, want_mode)
        items.append(SyncItem(name, str(target), "write"))
    return items


def status(env: dict[str, str] | None = None) -> dict:
    me = this_machine(env)
    man = load_manifest(env)
    entitled = [s["name"] for s in man["secrets"]
                if me and me.get("role") in (s.get("consumers") or [])]
    return {
        "has_identity": has_identity(),
        "recipient": identity_recipient() if has_identity() else None,
        "authorized": me is not None,
        "label": me.get("label") if me else None,
        "role": me.get("role") if me else None,
        "entitled": entitled,
        "total_secrets": len(man["secrets"]),
        "machines": len(load_recipients(env).get("machines", [])),
    }


@dataclass
class Check:
    name: str
    status: str          # ok | warn | fail
    detail: str = ""


def health_check(env: dict[str, str] | None = None) -> list[Check]:
    """Verify this machine's keyring setup end to end. Returns an ordered list of
    checks. The load-bearing one is the security-negative: for every box this
    machine is NOT entitled to, decryption MUST fail — if it ever succeeds, that
    is a ``fail`` (a leak), not a pass."""
    checks: list[Check] = []
    add = lambda n, s, d="": checks.append(Check(n, s, d))  # noqa: E731

    add("age installed", "ok" if age_crypto.age_available() else "fail",
        "" if age_crypto.age_available() else "install age (https://age-encryption.org)")

    if not has_identity():
        add("machine identity", "fail", "missing — run `murmurent keyring init`")
        return checks
    mode = stat.S_IMODE(identity_path().stat().st_mode)
    add("machine identity", "ok" if mode == 0o600 else "warn",
        f"{identity_path()} (mode 0{mode:o})"
        + ("" if mode == 0o600 else " — expected 0600"))

    kd = keyring_dir(env)
    if not kd.is_dir():
        add("lab_info/.keyring", "fail",
            f"{kd} missing — has a machine seeded secrets and pushed? did you pull?")
        return checks
    add("lab_info/.keyring", "ok", str(kd))

    me = this_machine(env)
    if me:
        add("authorised", "ok", f"label={me.get('label')}, role={me.get('role')}")
    else:
        add("authorised", "warn",
            "this machine's key is not in the roster yet — have an authorised "
            "machine run `keyring authorize`, then pull")

    man = load_manifest(env)
    add("manifest", "ok", f"{len(man['secrets'])} secret(s) declared")

    my_role = me.get("role") if me else None
    for s in man["secrets"]:
        name = s["name"]
        box = secret_box_path(name, env)
        entitled = my_role in (s.get("consumers") or [])
        if not box.is_file():
            add(f"secret:{name}", "warn", "box not on disk — run `keyring sync` (pull)")
            continue
        if entitled:
            try:
                plaintext = unlock_secret(name, env)
            except KeyringError as exc:
                add(f"secret:{name}", "fail", f"entitled but could not open: {exc}")
                continue
            target = _expand(s["target"])
            try:
                want_mode = int(str(s.get("mode", "0600")), 8)
            except ValueError:
                add(f"secret:{name}", "fail", f"invalid mode {s.get('mode')!r} in manifest")
                continue
            if not target.is_file():
                add(f"secret:{name}", "warn",
                    f"opens, but not unpacked yet — run `keyring sync --apply` (→ {target})")
            elif target.read_text(encoding="utf-8") != plaintext:
                add(f"secret:{name}", "warn",
                    f"opens, but {target} is out of date — run `keyring sync --apply`")
            elif stat.S_IMODE(target.stat().st_mode) != want_mode:
                add(f"secret:{name}", "warn",
                    f"unpacked at 0{stat.S_IMODE(target.stat().st_mode):o}, "
                    f"manifest wants 0{want_mode:o}")
            else:
                add(f"secret:{name}", "ok", f"opens + unpacked at {target} (0{want_mode:o})")
        else:
            # security-negative: this machine must NOT be able to open it
            try:
                unlock_secret(name, env)
                add(f"secret:{name}", "fail",
                    f"SECURITY: opened a box a {my_role!r} role must NOT open!")
            except KeyringError:
                add(f"secret:{name}", "ok", f"correctly refused (not for role {my_role!r})")
    return checks


def verify_repo(env: dict[str, str] | None = None) -> list[Check]:
    """Structural integrity of the ``.keyring`` store — needs NO private key, so it
    runs in CI or on any machine (distinct from :func:`health_check`, which
    decrypts with this machine's key). Checks the roster, manifest, and boxes are
    internally consistent: valid recipients/roles, no duplicate labels or secret
    names, every declared secret has a non-empty age box, and every box has at
    least one machine that could open it."""
    checks: list[Check] = []
    add = lambda n, s, d="": checks.append(Check(n, s, d))  # noqa: E731

    kd = keyring_dir(env)
    if not kd.is_dir():
        add("keyring present", "fail", f"no {kd}")
        return checks

    try:
        rec = load_recipients(env)
    except KeyringError as exc:
        add("recipients.yaml", "fail", str(exc))
        return checks
    machines = rec["machines"]
    labels = [m.get("label") for m in machines]
    recips = [m.get("recipient") for m in machines]
    roster_roles: set[str] = set()
    roster_issues: list[str] = []
    for m in machines:
        lbl, r, role = m.get("label"), m.get("recipient"), m.get("role")
        if not (lbl and r and role):
            roster_issues.append(f"{lbl or '?'}: missing label/recipient/role")
        elif not str(r).startswith("age1"):
            roster_issues.append(f"{lbl}: not an age recipient")
        elif role not in VALID_ROLES:
            roster_issues.append(f"{lbl}: unknown role {role!r}")
        else:
            roster_roles.add(role)
    for kind, seq in (("label", labels), ("recipient", recips)):
        dups = sorted({x for x in seq if x and seq.count(x) > 1})
        if dups:
            roster_issues.append(f"duplicate {kind}(s): {', '.join(map(str, dups))}")
    add("roster", "fail" if roster_issues else "ok",
        "; ".join(roster_issues) if roster_issues else f"{len(machines)} machine(s)")

    try:
        man = load_manifest(env)
    except KeyringError as exc:
        add("manifest.yaml", "fail", str(exc))
        return checks
    names = [s.get("name") for s in man["secrets"]]
    dup_names = sorted({x for x in names if x and names.count(x) > 1})
    add("manifest", "fail" if dup_names else "ok",
        f"duplicate secret name(s): {', '.join(map(str, dup_names))}" if dup_names
        else f"{len(man['secrets'])} secret(s)")

    for s in man["secrets"]:
        name = s.get("name") or "?"
        hard: list[str] = []
        soft: list[str] = []
        if not s.get("target"):
            hard.append("no target")
        try:
            int(str(s.get("mode", "0600")), 8)
        except ValueError:
            hard.append(f"bad mode {s.get('mode')!r}")
        cons = s.get("consumers") or []
        bad_roles = [c for c in cons if c not in VALID_ROLES]
        if bad_roles:
            hard.append(f"unknown consumer role(s) {bad_roles}")
        box = secret_box_path(name, env)
        if not box.is_file():
            hard.append("box missing on disk")
        else:
            body = box.read_text(encoding="utf-8", errors="replace")
            if not body.strip():
                hard.append("box is empty")
            elif "age-encryption.org" not in body and "BEGIN AGE" not in body:
                hard.append("box is not a valid age file")
        if not (set(cons) & roster_roles):
            soft.append("no authorised machine can open it")
        if hard:
            add(f"secret:{name}", "fail", "; ".join(hard + soft))
        elif soft:
            add(f"secret:{name}", "warn", "; ".join(soft))
        else:
            add(f"secret:{name}", "ok", f"box ok, opens for {cons}")

    declared = {s.get("name") for s in man["secrets"]}
    sd = secrets_dir(env)
    if sd.is_dir():
        for box in sorted(sd.glob("*.age")):
            if box.stem not in declared:
                add(f"orphan:{box.name}", "warn", "box on disk with no manifest entry")
    return checks


__all__ = [
    "KeyringError", "VALID_ROLES", "Check", "health_check", "verify_repo",
    "identity_path", "keyring_dir", "secrets_dir", "secret_box_path",
    "has_identity", "identity_recipient", "ensure_identity",
    "load_recipients", "save_recipients", "load_manifest", "save_manifest",
    "this_machine", "recipients_for", "lock_secret", "unlock_secret",
    "set_secret", "authorize", "rotate_secret", "revoke", "sync", "status",
    "SyncItem",
]
