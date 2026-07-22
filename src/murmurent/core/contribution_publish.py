"""
Purpose: publish ("state") a member's contribution to their group, and list the
contributions a member owns and the contributions their group has been offered.

A **contribution** is authored privately in a member's personal vault
(``<vault>/contributions/`` — see :mod:`contribution_spec` / :mod:`contribution_contract`). To
make it *known to the group* — an offered service or experiment other members
can build a choreography from — the member "states" it: the spec **and** its
contract are copied into the group's governance repo under ``contributions/`` (a
sibling of ``choreographies/``, which is likewise group-shared). Two things
then work that could not before:

  * other members see the offered contribution (the dashboard's group contribution pool), and
  * a choreography (also in the group repo) can resolve the contribution to check
    joinability, because the spec + contract now sit beside it.

This mirrors the Oracle publish flow (personal vault → group), and keeps the
personal vault the place a contribution is authored, the group repo the place it is
advertised.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from . import contribution_contract as _pc
from . import contribution_spec as _ps
from . import repo as _repo

GROUP_CONTRIBUTIONS_DIRNAME = "contributions"


class ContributionPublishError(RuntimeError):
    """Raised when a contribution cannot be stated to the group."""


def group_contributions_dir() -> Path:
    """The group governance repo's ``contributions/`` folder (stated contributions live here).

    Sibling of ``choreographies/`` in ``murmurent_lab_mgmt_<lab>``; resolved the
    same way (via :func:`repo.lab_mgmt_repo_root`). Not guaranteed to exist yet —
    :func:`state_contribution_to_group` creates it on first publish.
    """
    return _repo.lab_mgmt_repo_root() / GROUP_CONTRIBUTIONS_DIRNAME


def member_contributions_dir() -> Path | None:
    """The member's own ``contributions/`` folder (their personal vault), or ``None``
    when no vault is registered on this machine."""
    return _ps.default_spec_dir()


def _iter_specs(directory: Path | None) -> list[_ps.ContributionSpec]:
    """Parse every ``*_contribution.md`` under ``directory`` (best-effort; a file that
    fails to parse is skipped, not fatal)."""
    if directory is None or not Path(directory).is_dir():
        return []
    specs: list[_ps.ContributionSpec] = []
    for path in sorted(Path(directory).glob("*_contribution.md")):
        try:
            specs.append(_ps.ContributionSpec.from_file(path))
        except _ps.ContributionSpecError:
            continue
    return specs


def list_member_contributions() -> list[_ps.ContributionSpec]:
    """Every contribution this member has authored in their personal vault."""
    return _iter_specs(member_contributions_dir())


def list_group_contributions() -> list[_ps.ContributionSpec]:
    """Every contribution stated to the group (published into the group repo)."""
    return _iter_specs(group_contributions_dir())


def is_stated(contribution_slug: str) -> bool:
    """True when a contribution with this slug has already been stated to the group."""
    slug = _pc.slugify(contribution_slug)
    return (group_contributions_dir() / f"{slug}_contribution.md").is_file()


@dataclass(frozen=True)
class StateResult:
    spec_path: Path
    contract_path: Path
    slug: str


def state_contribution_to_group(reference: str) -> StateResult:
    """Copy a member's contribution (spec + its contract) into the group repo.

    ``reference`` is a contribution-spec path or slug, resolved in the member's vault.
    The spec's contract is resolved and copied too, and the published spec's
    ``contract`` field is rewritten to the contract's bare slug so it resolves
    locally beside the spec in the group ``contributions/`` folder (no dependency on
    the author's vault path). Idempotent: re-stating overwrites the group copy
    with the current vault version.

    Raises :class:`ContributionPublishError` when the spec or its contract can't be
    resolved (a contribution must carry a valid contract to be offered — joinability
    is defined entirely by the contract's ``candidate_key``).
    """
    spec_path = _ps.resolve_spec_reference(reference, member_contributions_dir())
    if spec_path is None:
        raise ContributionPublishError(
            f"contribution {reference!r} not found in your vault ({member_contributions_dir()})"
        )
    try:
        spec = _ps.ContributionSpec.from_file(spec_path)
    except _ps.ContributionSpecError as exc:
        raise ContributionPublishError(f"contribution {reference!r} could not be parsed: {exc}")

    contract = spec.resolved_contract()
    if contract is None:
        raise ContributionPublishError(
            f"contribution {reference!r} has no resolvable contract — a contribution must "
            "declare its output contract (candidate_key, metric, …) before it "
            "can be offered to the group."
        )

    dest_dir = group_contributions_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    contract_slug = _pc.slugify(contract.contribution or spec.contribution)
    contract_name = _pc.default_contract_filename(contract.contribution or spec.contribution)
    contract_path = dest_dir / contract_name
    contract_path.write_text(contract.to_markdown(), encoding="utf-8")

    # Rewrite the spec's contract reference to the bare slug so it resolves
    # beside the spec in the group folder, independent of the author's vault.
    spec.contract = contract_slug
    spec_slug = _pc.slugify(spec.contribution)
    spec_name = _ps.default_spec_filename(spec.contribution)
    published_spec = dest_dir / spec_name
    published_spec.write_text(spec.to_markdown(), encoding="utf-8")

    return StateResult(spec_path=published_spec, contract_path=contract_path, slug=spec_slug)
