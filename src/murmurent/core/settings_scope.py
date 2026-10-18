"""
Purpose: One register of every dashboard setting: whether it belongs to this
         machine, to you on all your machines, or to the whole lab, and where
         it is stored (issue #187).
Author: Mike Hallett (with Claude Code)
Date: 2026-10-18
Input: none; read by tests and documentation.
Output: :data:`REGISTER` and :func:`scope_of`.

Why a register. A setting that belongs to a person but is stored per machine
must be typed again on every machine, and one that belongs to a machine but
is shared breaks the other machines. Writing the scope of every setting down,
and failing a test when a new setting is added without a scope
(tests/test_settings_scope.py), keeps that decision visible.

The three scopes:

- ``machine``: true of this computer only, in ``~/.murmurent/machine.yaml``
  (folders, this machine's name). Never shared.
- ``person``: true of you everywhere. Your profile: in the lab roster
  (``members/<handle>.md``), written by the PI; a member's own edits travel in
  their personal vault and reach the roster through the PI (#187).
- ``lab``: true for everyone in the lab, in ``lab.md`` in the lab management
  repo, written by the PI.

``person-per-machine`` marks a setting that is really about you but is still
stored per machine: today, the names of folders inside your vault. They should
move to the vault; until then, set them the same way on each machine.
"""

from __future__ import annotations

MACHINE = "machine"
PERSON = "person"
LAB = "lab"
PERSON_PER_MACHINE = "person-per-machine"

#: (window, field) -> (scope, where it is stored)
REGISTER: dict[tuple[str, str], tuple[str, str]] = {}


def _add(window: str, scope: str, where: str, *fields: str) -> None:
    for f in fields:
        REGISTER[(window, f)] = (scope, where)


_ROSTER = "lab roster members/<handle>.md (PI); a member's edits: vault, then the PI"
_add("profile", PERSON, _ROSTER,
     "official_handle", "slack_handle", "email", "orcid", "bluesky", "github", "osf",
     "website", "office", "dry_lab", "wet_labs", "address", "city", "department",
     "git_logins")
# The profile window still carries these vault fields from an older layout;
# they are saved per machine, like the machine window's.
_add("profile", MACHINE, "~/.murmurent/machine.yaml",
     "obsidian_vault_path", "obsidian_vault_name")
_add("profile", PERSON_PER_MACHINE, "~/.murmurent/machine.yaml",
     "notebook_subfolder", "oracle_subfolder")

_MACHINE_FILE = "~/.murmurent/machine.yaml"
_add("machine", MACHINE, _MACHINE_FILE,
     "machine_name", "wigamig_base", "obsidian_vault_path", "obsidian_vault_name",
     "lab_base", "repos_root", "data_immutable_name", "data_append_only_name")
_add("machine", PERSON_PER_MACHINE, _MACHINE_FILE,
     "notebook_subfolder", "oracle_subfolder", "murmurent_data_subfolder")

_add("lab", LAB, "lab.md in the lab management repo (PI)",
     "name", "display_name", "pi_handle", "website", "admins", "lab_base",
     "git_providers", "github_org", "git_repos_subpath", "slack_workspace",
     "slack_invite_url", "space_audit", "notebook_host", "notebook_path",
     "obsidian_host", "obsidian_path", "notebook_large_files_path",
     "lab_oracle_vault")


def scope_of(window: str, field: str) -> str | None:
    """The scope of one setting, or None if it is not registered."""
    hit = REGISTER.get((window, field))
    return hit[0] if hit else None
