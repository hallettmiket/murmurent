"""
Purpose: Decentralized identity cards — put a member's role onto THEIR machine.

The mayor registers members centrally (in the centre registry on the mayor's
machine), but a member's own machine must independently know their role so their
dashboard login resolves correctly and an arbitrary netname is refused. This
module:

  - ``build_card(handle)`` (MAYOR side): reads the centre registry, finds the
    handle's role(s), and produces a small, SCOPED identity card — the member's
    netname + only their own group's entry. A member never receives the whole
    centre's data.
  - ``import_card(card)`` (MEMBER side): writes the card to ``~/.murmurent``,
    materializes a scoped ``lab_info/_registry.yaml`` pointing each group at
    its one records repo location (``<repos>/murmurent_lab_mgmt_<group>``),
    and stamps the machine's netname in ``~/.murmurent/user``. Nothing is
    invented when the clone is missing: the card itself proves membership,
    and the import says where to clone.
  - ``local_card()``: read this machine's card (for netname enforcement).

Decentralized by design: no shared server or GitHub repo is required — the
mayor hands the member a card (e.g. attached to the invite), the member imports
it. Matches murmurent's choreography-not-orchestration ethos.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import yaml

from . import registrar as _R

# Versions the SHAPE of an identity card — independent of the murmurent release
# version. Bump only when the card format changes, not to match a release. (#24)
CARD_VERSION = 1


def _home() -> Path:
    """The machine's ~/.murmurent root (identity + user files live here)."""
    import os
    return Path(os.environ.get("MURMURENT_HOME", str(Path.home() / ".murmurent")))


def identity_path() -> Path:
    return _home() / "identity.yaml"


# ---------------------------------------------------------------------------
# Mayor side — build a scoped card for one handle
# ---------------------------------------------------------------------------

def build_card(handle: str, *, env: dict[str, str] | None = None,
               issued_by: str = "", issued_at: str | None = None) -> dict:
    """Build a scoped identity card for ``handle`` from the centre registry.

    ``roles`` is a list of ``{kind, group, pi}`` where kind is one of
    ``lab_pi`` / ``core_leader`` / ``member`` / ``registrar``. Raises ValueError
    if the handle holds no role in this centre (nothing to card)."""
    from . import centre_init as _ci
    norm = _R._normalize(handle)
    if not norm:
        raise ValueError("empty handle")
    reg = _R.read_registry(env)
    roles: list[dict] = []
    for l in reg.labs:
        if str(getattr(l, "status", "active")) == "active" and _R._normalize(l.pi) == norm:
            roles.append({"kind": "lab_pi", "group": l.name, "pi": f"@{norm}"})
    for c in reg.cores:
        if str(getattr(c, "status", "active")) == "active" and _R._normalize(c.pi) == norm:
            roles.append({"kind": "core_leader", "group": c.name, "pi": f"@{norm}"})
    # Plain membership: a group whose members/<handle>.md exists but they don't
    # lead. Reuse lab_mgmt_path_for_handle (PI match first, else member probe).
    led = {r["group"] for r in roles}
    match = _R.lab_mgmt_path_for_handle(norm, env)
    if match and match[0] not in led:
        gname = match[0]
        entry = next((g for g in [*reg.labs, *reg.cores] if g.name == gname), None)
        if entry is not None:
            kind = "core" if any(c.name == gname for c in reg.cores) else "lab"
            roles.append({"kind": "member", "group": gname, "pi": entry.pi,
                          "group_kind": kind})
    if _R.is_registrar(norm):
        roles.append({"kind": "registrar"})
    if not roles:
        raise ValueError(f"@{norm} holds no role in this centre — nothing to card")
    centre = _ci.read_centre(env=env)
    return {
        "version": CARD_VERSION,
        "netname": norm,
        "centre": (getattr(centre, "unique_name", "") or getattr(centre, "name", "")
                   if centre else ""),
        "roles": roles,
        "issued_by": _R._normalize(issued_by) or "",
        "issued_at": issued_at or _dt.date.today().isoformat(),
    }


def card_yaml(card: dict) -> str:
    return yaml.safe_dump(card, sort_keys=False, allow_unicode=True)


def parse_card(text: str) -> dict:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict) or not data.get("netname"):
        raise ValueError("not a valid identity card (missing netname)")
    return data


# ---------------------------------------------------------------------------
# Member side — import a card + materialize a scoped local registry
# ---------------------------------------------------------------------------

def _group_kind(role: dict) -> str:
    if role["kind"] == "core_leader":
        return "core"
    if role["kind"] == "member":
        return str(role.get("group_kind") or "lab")
    return "lab"


def import_card(card: dict, *, env: dict[str, str] | None = None,
                remotes: dict[str, str] | None = None) -> list[str]:
    """Materialize a card onto this machine.

    Writes ``~/.murmurent/identity.yaml`` + ``~/.murmurent/user`` and a SCOPED
    ``lab_info/_registry.yaml`` whose every group points at the canonical
    records repo path, so the role resolver + scoping gate resolve this
    member locally. ``remotes`` maps a group to the git URL of its records
    repo, when the caller knows it (a member-card bundle carries it), so the
    "clone it" action can be copied as is. Returns human-readable actions.
    """
    card = parse_card(card) if isinstance(card, str) else card
    netname = _R._normalize(card["netname"])
    actions: list[str] = []

    # 1. netname (the machine's owner) + the card itself.
    home = _home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "user").write_text(netname + "\n", encoding="utf-8")
    identity_path().write_text(card_yaml(card), encoding="utf-8")
    actions.append(f"netname set to @{netname} (~/.murmurent/user)")

    # 2. Scoped registry + minimal lab-mgmt per group.
    lab_info = _R.lab_info_root(env)
    labs: dict[str, dict] = {}
    cores: dict[str, dict] = {}
    registrars: list[str] = []
    from . import repo as _repo
    for role in card.get("roles", []):
        if role.get("kind") == "registrar":
            registrars.append(netname)
            actions.append("recorded as a centre registrar")
            continue
        group = role["group"]
        kind = _group_kind(role)
        gpi = _R._normalize(role.get("pi") or netname)
        # One place per group: <repos>/murmurent_lab_mgmt_<group>. The PI's
        # copy is created there by pi-init and pushed to GitHub; a member
        # clones it there, read-only. The dashboard and the terminal both
        # resolve through this entry, so they can never follow different labs.
        path = _repo.lab_repo_path(group)
        entry = {"pi": f"@{gpi}", "lab_mgmt_path": str(path), "status": "active"}
        (cores if kind == "core" else labs)[group] = entry
        if gpi == netname:
            actions.append(f"registered {kind} '{group}' → {path}")
        elif path.is_dir():
            actions.append(f"registered {kind} '{group}' → {path} (your copy of the lab records)")
        else:
            hint = _repo.records_clone_hint(group, remote=(remotes or {}).get(group, ""))
            actions.append(f"registered {kind} '{group}' → {path} (not on this machine yet). {hint}")

    reg_doc = {
        "version": 1,
        "registrars": registrars,
        "labs": labs,
        "cores": cores,
        "collaborations": {},
    }
    lab_info.mkdir(parents=True, exist_ok=True)
    (lab_info / "_registry.yaml").write_text(
        yaml.safe_dump(reg_doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    actions.append(f"scoped registry written ({len(labs)} lab(s), {len(cores)} core(s))")
    return actions


def local_card(env: dict[str, str] | None = None) -> dict | None:
    """This machine's identity card, or None if not imported yet."""
    p = identity_path()
    if not p.is_file():
        return None
    try:
        return parse_card(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def machine_netname(env: dict[str, str] | None = None) -> str:
    """The netname this machine's identity card belongs to (or "")."""
    card = local_card(env)
    return _R._normalize(card.get("netname")) if card else ""


__all__ = [
    "build_card", "import_card", "card_yaml", "parse_card",
    "local_card", "machine_netname", "identity_path",
]
