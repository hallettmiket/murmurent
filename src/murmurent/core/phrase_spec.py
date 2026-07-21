"""
Purpose: The phrase spec — an authored phrase offered by a member into a
         compositional choreography. A phrase is a small graph of *steps*
         (analyses that transform data) and *transitions* (rank/filter/select
         decisions on a step's output) that produces an output conforming to
         its Phase-1 output contract (:mod:`murmurent.core.phrase_contract`).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: Keyword args (constructing a spec) or a schema-validated markdown entry
       (YAML frontmatter + optional body), mirroring the phrase contract.
Output: :class:`PhraseSpec` instances; markdown serialization via
        ``to_markdown()`` / ``from_markdown()`` / ``from_file()``; and a
        ``validate()`` that returns a list of human-readable problems (empty ==
        valid), including resolving + validating the referenced output contract.

Boundary: this module defines and validates the *authored* phrase artefact
only. It does NOT execute steps, apply transitions, or judge outputs — those
are later choreography phases. See ``docs/phrases.md`` / ``docs/choreography.md``.

Path resolution (for the default write location):
  - ``$MURMURENT_PHRASE_SPEC_DIR`` if set, else
  - ``<personal-vault>/phrases/`` (the same folder the phrase contract uses).
  - ``default_spec_dir()`` returns ``None`` when no vault is registered, letting
    callers fall back to an explicit ``--out`` path or stdout.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import phrase_contract as _pc
from .frontmatter import dump_document, parse_file, parse_text

# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

#: A step either invokes an agent or runs a script/command.
STEP_KIND_VOCAB: frozenset[str] = frozenset({"agent", "script"})

#: A transition inspects a step's output and makes one of these decisions.
TRANSITION_KIND_VOCAB: frozenset[str] = frozenset({"rank", "filter", "select"})

#: Frontmatter fields that must be present and non-empty for a valid spec.
REQUIRED_FIELDS: tuple[str, ...] = ("phrase", "author", "question", "contract")

#: Marker written into the frontmatter so tooling can recognise the artefact.
KIND = "phrase_spec"

# Re-export the slug helper so callers have one import surface.
slugify = _pc.slugify


class PhraseSpecError(ValueError):
    """Raised when a phrase spec cannot be parsed from markdown."""


@dataclass
class Step:
    """One analysis in a phrase: transforms an input ``X'`` into ``X''``.

    ``kind`` is ``agent`` (``run`` names an agent) or ``script`` (``run`` is a
    command). ``description`` is a short human-readable note on what it does.
    """

    name: str
    kind: str
    run: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "run": self.run,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Step":
        return cls(
            name=str(d.get("name", "") or ""),
            kind=str(d.get("kind", "") or ""),
            run=str(d.get("run", "") or ""),
            description=str(d.get("description", "") or ""),
        )


@dataclass
class Transition:
    """A decision applied to a step's output: rank, filter, or select.

    ``params`` is a free dict of decision parameters (e.g. ``{"top": 100}``).
    """

    name: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "kind": self.kind, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Transition":
        params = d.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        return cls(
            name=str(d.get("name", "") or ""),
            kind=str(d.get("kind", "") or ""),
            params=params,
        )


@dataclass
class PhraseSpec:
    """An authored phrase: a small graph of steps + transitions + a contract.

    The spec references its Phase-1 output contract (by relative path or slug);
    :meth:`validate` resolves that reference and validates the contract too, so
    an authored phrase and the shape of what it produces stay consistent.
    """

    phrase: str
    author: str
    question: str
    contract: str
    steps: list[Step] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    #: Optional path (relative to the spec) to the produced output table — set
    #: once the phrase has been run. Absent on a freshly-authored spec.
    output: str = ""
    notes: str = ""
    #: Set by :meth:`from_file`; used as the default base dir for resolving the
    #: (possibly relative) contract reference during :meth:`validate`.
    source: Path | None = field(default=None, compare=False)

    # -- validation --------------------------------------------------------

    def validate(self, base_dir: str | Path | None = None) -> list[str]:
        """Return a list of problems; an empty list means the spec is valid.

        Checks (mechanical only — this does not judge scientific merit):
          - every required field is present and non-empty;
          - ``author`` is a handle of the form ``@name``;
          - ``steps`` is non-empty and each step has a name, a valid ``kind``
            (``agent`` | ``script``), and a non-empty ``run``;
          - each transition has a name and a valid ``kind``
            (``rank`` | ``filter`` | ``select``);
          - the referenced ``contract`` resolves to a file that is itself a
            valid :class:`~murmurent.core.phrase_contract.PhraseContract`;
          - **when an ``output`` is set** (the phrase has been run), the output
            table conforms to the referenced contract
            (:func:`murmurent.core.phrase_output.validate_output`). ``output`` is
            optional — a spec authored before it is run is still valid.

        ``base_dir`` roots relative contract/output references; it defaults to
        the directory the spec was read from (``source``) or the current dir.
        """
        problems: list[str] = []

        for name in REQUIRED_FIELDS:
            value = getattr(self, name, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                problems.append(f"missing required field: {name}")

        if self.author and not self.author.startswith("@"):
            problems.append(
                f"author must be a handle of the form '@name' (got {self.author!r})"
            )

        # Steps: ordered, non-empty, each well-formed.
        if not self.steps:
            problems.append("steps must be a non-empty, ordered list")
        for i, step in enumerate(self.steps):
            label = step.name or f"#{i + 1}"
            if not step.name.strip():
                problems.append(f"step {label}: missing name")
            if not step.run.strip():
                problems.append(f"step {label}: missing run (agent name or command)")
            if step.kind not in STEP_KIND_VOCAB:
                allowed = ", ".join(sorted(STEP_KIND_VOCAB))
                problems.append(
                    f"step {label}: unknown kind {step.kind!r} (allowed: {allowed})"
                )

        # Transitions: optional, but each well-formed if present.
        for i, tr in enumerate(self.transitions):
            label = tr.name or f"#{i + 1}"
            if not tr.name.strip():
                problems.append(f"transition {label}: missing name")
            if tr.kind not in TRANSITION_KIND_VOCAB:
                allowed = ", ".join(sorted(TRANSITION_KIND_VOCAB))
                problems.append(
                    f"transition {label}: unknown kind {tr.kind!r} (allowed: {allowed})"
                )

        # Referenced output contract must resolve + be valid.
        if self.contract and self.contract.strip():
            problems.extend(self._validate_contract(base_dir))

        # Produced output table (optional): validate against the contract only
        # when present — a spec may be authored before the phrase is ever run.
        if self.output and self.output.strip():
            problems.extend(self._validate_output(base_dir))

        return problems

    def _validate_contract(self, base_dir: str | Path | None) -> list[str]:
        base = self._resolve_base_dir(base_dir)
        path = _pc.resolve_contract_reference(self.contract, base)
        if path is None:
            return [
                f"referenced contract {self.contract!r} could not be resolved "
                f"(looked for a path or a <slug>_contract.md)"
            ]
        try:
            contract = _pc.PhraseContract.from_file(path)
        except _pc.PhraseContractError as exc:
            return [f"referenced contract {path} could not be parsed: {exc}"]
        return [
            f"referenced contract {path.name}: {p}" for p in contract.validate()
        ]

    def _validate_output(self, base_dir: str | Path | None) -> list[str]:
        from . import phrase_output as _po  # deferred: keeps the import surface small

        contract = self.resolved_contract(base_dir)
        if contract is None:
            # The contract problem is already reported by _validate_contract;
            # without it there is nothing to validate the output against.
            return []
        path = self.resolved_output(base_dir)
        if path is None:
            return [
                f"declared output {self.output!r} could not be resolved "
                f"(looked for a path relative to the spec)"
            ]
        return [f"output {path.name}: {p}" for p in _po.validate_output(contract, path)]

    def resolved_output(self, base_dir: str | Path | None = None) -> Path | None:
        """Resolve the produced output table path, or ``None`` if not found."""
        if not (self.output and self.output.strip()):
            return None
        base = self._resolve_base_dir(base_dir)
        p = Path(self.output).expanduser()
        for cand in ([p] if p.is_absolute() else [base / p, Path.cwd() / p]):
            if cand.is_file():
                return cand
        return None

    def _resolve_base_dir(self, base_dir: str | Path | None) -> Path:
        if base_dir is not None:
            return Path(base_dir).expanduser()
        if self.source is not None:
            return Path(self.source).expanduser().parent
        return Path.cwd()

    def is_valid(self, base_dir: str | Path | None = None) -> bool:
        """Convenience: ``True`` when :meth:`validate` finds no problems."""
        return not self.validate(base_dir)

    def resolved_contract(
        self, base_dir: str | Path | None = None
    ) -> _pc.PhraseContract | None:
        """Load the referenced contract, or ``None`` if it cannot be resolved."""
        base = self._resolve_base_dir(base_dir)
        path = _pc.resolve_contract_reference(self.contract, base)
        if path is None:
            return None
        try:
            return _pc.PhraseContract.from_file(path)
        except _pc.PhraseContractError:
            return None

    # -- serialization -----------------------------------------------------

    def to_frontmatter(self) -> dict[str, Any]:
        """The ordered frontmatter mapping this spec serializes to.

        The ``output`` key is emitted only once the phrase has been run (an
        output is set), so a freshly-authored spec's serialization is unchanged.
        """
        meta: dict[str, Any] = {
            "kind": KIND,
            "phrase": self.phrase,
            "author": self.author,
            "question": self.question,
            "contract": self.contract,
            "steps": [s.to_dict() for s in self.steps],
            "transitions": [t.to_dict() for t in self.transitions],
        }
        if self.output and self.output.strip():
            meta["output"] = self.output
        return meta

    def to_markdown(self) -> str:
        """Serialize to a markdown entry: YAML frontmatter + optional body."""
        body = self.notes.strip() + "\n" if self.notes.strip() else ""
        return dump_document(self.to_frontmatter(), body)

    @classmethod
    def from_meta(
        cls, meta: dict[str, Any], body: str = "", source: Path | None = None
    ) -> "PhraseSpec":
        """Build a spec from a parsed frontmatter mapping + body text."""
        if not isinstance(meta, dict):
            raise PhraseSpecError("phrase spec frontmatter must be a mapping")
        steps_raw = meta.get("steps") or []
        trans_raw = meta.get("transitions") or []
        steps = [Step.from_dict(s) for s in steps_raw if isinstance(s, dict)]
        transitions = [
            Transition.from_dict(t) for t in trans_raw if isinstance(t, dict)
        ]
        return cls(
            phrase=str(meta.get("phrase", "") or ""),
            author=str(meta.get("author", "") or ""),
            question=str(meta.get("question", "") or ""),
            contract=str(meta.get("contract", "") or ""),
            steps=steps,
            transitions=transitions,
            output=str(meta.get("output", "") or ""),
            notes=body.strip(),
            source=source,
        )

    @classmethod
    def from_markdown(cls, text: str) -> "PhraseSpec":
        """Parse a spec from a markdown string (frontmatter + body)."""
        doc = parse_text(text)
        if not doc.meta:
            raise PhraseSpecError(
                "no YAML frontmatter found — a phrase spec needs a '---' block"
            )
        return cls.from_meta(doc.meta, doc.body)

    @classmethod
    def from_file(cls, path: str | Path) -> "PhraseSpec":
        """Read and parse a spec markdown file (records ``source`` for resolution)."""
        p = Path(path)
        doc = parse_file(p)
        if not doc.meta:
            raise PhraseSpecError(
                f"no YAML frontmatter found in {path} — not a phrase spec"
            )
        return cls.from_meta(doc.meta, doc.body, source=p)


# ---------------------------------------------------------------------------
# Default write location + reference resolution
# ---------------------------------------------------------------------------

ENV_SPEC_DIR = "MURMURENT_PHRASE_SPEC_DIR"


def default_spec_dir() -> Path | None:
    """Where ``murmurent phrase spec new`` writes by default.

    ``$MURMURENT_PHRASE_SPEC_DIR`` wins; otherwise the same ``phrases/`` folder
    the phrase contract uses (beside the personal Oracle dir). Returns ``None``
    when no vault is registered, so the caller can fall back to ``--out``/stdout.
    """
    pin = os.environ.get(ENV_SPEC_DIR, "").strip()
    if pin:
        return Path(pin).expanduser()
    return _pc.default_contract_dir()


def default_spec_filename(phrase: str) -> str:
    """The default basename for a spec file, derived from the phrase slug."""
    slug = slugify(phrase) or "phrase"
    return f"{slug}_phrase.md"


def resolve_spec_reference(
    ref: str, base_dir: str | Path | None = None
) -> Path | None:
    """Resolve a phrase-spec reference (relative/absolute path, or a slug).

    Tries, in order: the ref as an explicit path (absolute, then under
    ``base_dir``, then the cwd), then a ``<slug>_phrase.md`` file under
    ``base_dir`` and under :func:`default_spec_dir`. Returns ``None`` if nothing
    on disk matches.
    """
    ref = (ref or "").strip()
    if not ref:
        return None
    base = Path(base_dir).expanduser() if base_dir is not None else None
    candidates: list[Path] = []
    p = Path(ref).expanduser()
    if p.is_absolute():
        candidates.append(p)
    else:
        if base is not None:
            candidates.append(base / p)
        candidates.append(Path.cwd() / p)
    if "/" not in ref and not ref.endswith(".md"):
        fname = default_spec_filename(ref)
        if base is not None:
            candidates.append(base / fname)
        d = default_spec_dir()
        if d is not None:
            candidates.append(d / fname)
    for c in candidates:
        if c.is_file():
            return c
    return None
