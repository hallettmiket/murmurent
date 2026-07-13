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
  - ``import_card(card)`` (MEMBER side): writes the card to ``~/.murmurent`` and
    materializes a scoped ``lab_info/_registry.yaml`` (+ a minimal lab-mgmt) so
    the existing role resolver / scoping gate work locally, and stamps the
    machine's netname in ``~/.murmurent/user``.
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


def import_card(card: dict, *, env: dict[str, str] | None = None) -> list[str]:
    """Materialize a card onto this machine.

    Writes ``~/.murmurent/identity.yaml`` + ``~/.murmurent/user`` and a SCOPED
    ``lab_info/_registry.yaml`` (+ a minimal lab-mgmt dir per group) so the
    existing role resolver + scoping gate resolve this member locally. Returns
    a list of human-readable actions.
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
        if gpi == netname:
            # This machine's owner IS this group's PI/leader. The authoritative
            # lab-mgmt is their single ~/repos clone (created + version-controlled
            # by pi-init / self_issue, and pushable to GitHub) — NOT a second copy
            # under lab_info/. Point the registry at that one canonical location so
            # the dashboard (registry) and the CLI (pinned pointer) never diverge.
            # The clone + the PI's member record are written by self_issue.
            canonical = _repo._pinned_lab_mgmt_path() or _repo.lab_repo_path(group)
            entry = {"pi": f"@{gpi}", "lab_mgmt_path": str(canonical), "status": "active"}
            (cores if kind == "core" else labs)[group] = entry
            actions.append(f"registered {kind} '{group}' → {canonical}")
            continue
        gdir = lab_info / ("cores" if kind == "core" else "labs") / group / "lab-mgmt"
        (gdir / "members").mkdir(parents=True, exist_ok=True)
        (gdir / "lab.md").write_text(
            f"---\nlab: {group}\nname: {group}\npi: '@{gpi}'\nkind: {kind}\n---\n\n# {group}\n",
            encoding="utf-8")
        # This member's own record (so is_member resolves).
        (gdir / "members" / f"{netname}.md").write_text(
            f"---\nhandle: '@{netname}'\nstatus: active\nlab: {group}\n---\n\n# @{netname}\n",
            encoding="utf-8")
        entry = {"pi": f"@{gpi}", "lab_mgmt_path": str(gdir), "status": "active"}
        (cores if kind == "core" else labs)[group] = entry
        actions.append(f"materialized {kind} '{group}' (role: {role['kind']})")

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
