"""
Purpose: publish ("state") a member's phrase to their group, and list the
phrases a member owns and the phrases their group has been offered.

A **phrase** is authored privately in a member's personal vault
(``<vault>/phrases/`` — see :mod:`phrase_spec` / :mod:`phrase_contract`). To
make it *known to the group* — an offered service or experiment other members
can build a choreography from — the member "states" it: the spec **and** its
contract are copied into the group's governance repo under ``phrases/`` (a
sibling of ``choreographies/``, which is likewise group-shared). Two things
then work that could not before:

  * other members see the offered phrase (the dashboard's group phrase pool), and
  * a choreography (also in the group repo) can resolve the phrase to check
    joinability, because the spec + contract now sit beside it.

This mirrors the Oracle publish flow (personal vault → group), and keeps the
personal vault the place a phrase is authored, the group repo the place it is
advertised.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from . import phrase_contract as _pc
from . import phrase_spec as _ps
from . import repo as _repo

GROUP_PHRASES_DIRNAME = "phrases"


class PhrasePublishError(RuntimeError):
    """Raised when a phrase cannot be stated to the group."""


def group_phrases_dir() -> Path:
    """The group governance repo's ``phrases/`` folder (stated phrases live here).

    Sibling of ``choreographies/`` in ``murmurent_lab_mgmt_<lab>``; resolved the
    same way (via :func:`repo.lab_mgmt_repo_root`). Not guaranteed to exist yet —
    :func:`state_phrase_to_group` creates it on first publish.
    """
    return _repo.lab_mgmt_repo_root() / GROUP_PHRASES_DIRNAME


def member_phrases_dir() -> Path | None:
    """The member's own ``phrases/`` folder (their personal vault), or ``None``
    when no vault is registered on this machine."""
    return _ps.default_spec_dir()


def _iter_specs(directory: Path | None) -> list[_ps.PhraseSpec]:
    """Parse every ``*_phrase.md`` under ``directory`` (best-effort; a file that
    fails to parse is skipped, not fatal)."""
    if directory is None or not Path(directory).is_dir():
        return []
    specs: list[_ps.PhraseSpec] = []
    for path in sorted(Path(directory).glob("*_phrase.md")):
        try:
            specs.append(_ps.PhraseSpec.from_file(path))
        except _ps.PhraseSpecError:
            continue
    return specs


def list_member_phrases() -> list[_ps.PhraseSpec]:
    """Every phrase this member has authored in their personal vault."""
    return _iter_specs(member_phrases_dir())


def list_group_phrases() -> list[_ps.PhraseSpec]:
    """Every phrase stated to the group (published into the group repo)."""
    return _iter_specs(group_phrases_dir())


def is_stated(phrase_slug: str) -> bool:
    """True when a phrase with this slug has already been stated to the group."""
    slug = _pc.slugify(phrase_slug)
    return (group_phrases_dir() / f"{slug}_phrase.md").is_file()


@dataclass(frozen=True)
class StateResult:
    spec_path: Path
    contract_path: Path
    slug: str


def state_phrase_to_group(reference: str) -> StateResult:
    """Copy a member's phrase (spec + its contract) into the group repo.

    ``reference`` is a phrase-spec path or slug, resolved in the member's vault.
    The spec's contract is resolved and copied too, and the published spec's
    ``contract`` field is rewritten to the contract's bare slug so it resolves
    locally beside the spec in the group ``phrases/`` folder (no dependency on
    the author's vault path). Idempotent: re-stating overwrites the group copy
    with the current vault version.

    Raises :class:`PhrasePublishError` when the spec or its contract can't be
    resolved (a phrase must carry a valid contract to be offered — joinability
    is defined entirely by the contract's ``candidate_key``).
    """
    spec_path = _ps.resolve_spec_reference(reference, member_phrases_dir())
    if spec_path is None:
        raise PhrasePublishError(
            f"phrase {reference!r} not found in your vault ({member_phrases_dir()})"
        )
    try:
        spec = _ps.PhraseSpec.from_file(spec_path)
    except _ps.PhraseSpecError as exc:
        raise PhrasePublishError(f"phrase {reference!r} could not be parsed: {exc}")

    contract = spec.resolved_contract()
    if contract is None:
        raise PhrasePublishError(
            f"phrase {reference!r} has no resolvable contract — a phrase must "
            "declare its output contract (candidate_key, metric, …) before it "
            "can be offered to the group."
        )

    dest_dir = group_phrases_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)

    contract_slug = _pc.slugify(contract.phrase or spec.phrase)
    contract_name = _pc.default_contract_filename(contract.phrase or spec.phrase)
    contract_path = dest_dir / contract_name
    contract_path.write_text(contract.to_markdown(), encoding="utf-8")

    # Rewrite the spec's contract reference to the bare slug so it resolves
    # beside the spec in the group folder, independent of the author's vault.
    spec.contract = contract_slug
    spec_slug = _pc.slugify(spec.phrase)
    spec_name = _ps.default_spec_filename(spec.phrase)
    published_spec = dest_dir / spec_name
    published_spec.write_text(spec.to_markdown(), encoding="utf-8")

    return StateResult(spec_path=published_spec, contract_path=contract_path, slug=spec_slug)
