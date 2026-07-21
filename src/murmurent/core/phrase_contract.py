"""
Purpose: The phrase output-contract — the typed data contract that declares
         the shape and meaning of a phrase's output so heterogeneous phrase
         outputs (different metrics, units, directions) can be aligned on a
         shared candidate identity and combined by a choreography judge.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: Keyword args (constructing a contract) or a schema-validated markdown
       entry (YAML frontmatter + optional body), mirroring Oracle entries.
Output: :class:`PhraseContract` instances; markdown serialization via
        ``to_markdown()`` / ``from_markdown()``; a ``validate()`` that returns
        a list of human-readable problems (empty == valid).

Boundary: this module defines and validates the contract artefact only. It does
NOT run phrases, align outputs, or judge them — those are later choreography
phases. See ``docs/phrases.md`` and ``docs/choreography.md``.

Path resolution (for the default write location):
  - ``$MURMURENT_PHRASE_CONTRACT_DIR`` if set, else
  - ``<personal-vault>/phrases/`` (sibling of the Oracle dir, resolved the
    same way ``murmurent.core.oracle_publish.personal_oracle_dir`` resolves).
  - ``default_contract_dir()`` returns ``None`` when no vault is registered,
    letting callers fall back to an explicit ``--out`` path or stdout.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .frontmatter import dump_document, parse_file, parse_text

# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

#: Candidate-identity spaces a contract may name. The escape hatch is a value
#: of the form ``other:<free-text>`` for identity spaces outside this set.
CANDIDATE_KEY_VOCAB: frozenset[str] = frozenset(
    {"inchikey", "smiles", "gene_symbol", "uniprot"}
)
OTHER_PREFIX = "other:"

#: Frontmatter fields that must be present and non-empty for a valid contract.
REQUIRED_FIELDS: tuple[str, ...] = (
    "phrase",
    "author",
    "question",
    "candidate_key",
    "metric",
    "units",
    "direction",
    "uncertainty",
)

#: Marker written into the frontmatter so tooling can recognise the artefact.
KIND = "phrase_contract"

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


class Direction(str, Enum):
    """Whether a higher or lower value of the reported metric is 'better'.

    Subclassing ``str`` keeps the enum YAML-friendly: it serializes to its
    bare value (``higher_better``) rather than ``Direction.HIGHER_BETTER``.
    """

    HIGHER_BETTER = "higher_better"
    LOWER_BETTER = "lower_better"


class PhraseContractError(ValueError):
    """Raised when a contract cannot be parsed from markdown."""


def slugify(text: str) -> str:
    """Lowercase ``text`` to a filesystem-safe slug (``a-z0-9_`` + ``-``)."""
    return _SLUG_RE.sub("-", text.strip().lower()).strip("-_")


def candidate_key_ok(value: str) -> bool:
    """True when ``value`` is in the controlled vocab or a non-empty escape."""
    if value in CANDIDATE_KEY_VOCAB:
        return True
    if value.startswith(OTHER_PREFIX):
        return bool(value[len(OTHER_PREFIX):].strip())
    return False


@dataclass
class PhraseContract:
    """A phrase's typed output contract (a Tier-2, schema-validated artefact).

    The fields declare *what* the phrase reports and *how to read it*, so two
    phrases contributing to the same question can be joined on
    ``candidate_key`` and combined even when their ``metric`` differs.
    """

    phrase: str
    author: str
    question: str
    candidate_key: str
    metric: str
    units: str
    direction: str = Direction.HIGHER_BETTER.value
    uncertainty: str = "none"
    tags: list[str] = field(default_factory=list)
    notes: str = ""

    # -- validation --------------------------------------------------------

    def validate(self) -> list[str]:
        """Return a list of problems; an empty list means the contract is valid.

        Checks (mechanical only — this does not judge scientific merit):
          - every required field is present and non-empty;
          - ``author`` is a handle of the form ``@name``;
          - ``direction`` is one of the :class:`Direction` values;
          - ``candidate_key`` is in :data:`CANDIDATE_KEY_VOCAB` or a non-empty
            ``other:<free-text>`` escape.
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

        if self.direction and self.direction not in {d.value for d in Direction}:
            allowed = ", ".join(d.value for d in Direction)
            problems.append(
                f"unknown direction {self.direction!r} (allowed: {allowed})"
            )

        if self.candidate_key and not candidate_key_ok(self.candidate_key):
            allowed = ", ".join(sorted(CANDIDATE_KEY_VOCAB))
            problems.append(
                f"candidate_key {self.candidate_key!r} not in vocabulary "
                f"({allowed}) and not an 'other:<text>' escape"
            )

        return problems

    def is_valid(self) -> bool:
        """Convenience: ``True`` when :meth:`validate` finds no problems."""
        return not self.validate()

    # -- serialization -----------------------------------------------------

    def to_frontmatter(self) -> dict[str, Any]:
        """The ordered frontmatter mapping this contract serializes to."""
        return {
            "kind": KIND,
            "phrase": self.phrase,
            "author": self.author,
            "question": self.question,
            "candidate_key": self.candidate_key,
            "metric": self.metric,
            "units": self.units,
            "direction": self.direction,
            "uncertainty": self.uncertainty,
            "tags": list(self.tags),
        }

    def to_markdown(self) -> str:
        """Serialize to a markdown entry: YAML frontmatter + optional body."""
        body = self.notes.strip() + "\n" if self.notes.strip() else ""
        return dump_document(self.to_frontmatter(), body)

    @classmethod
    def from_meta(cls, meta: dict[str, Any], body: str = "") -> "PhraseContract":
        """Build a contract from a parsed frontmatter mapping + body text."""
        if not isinstance(meta, dict):
            raise PhraseContractError("contract frontmatter must be a mapping")
        tags_raw = meta.get("tags") or []
        if isinstance(tags_raw, str):
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        else:
            tags = [str(t) for t in tags_raw]
        return cls(
            phrase=str(meta.get("phrase", "") or ""),
            author=str(meta.get("author", "") or ""),
            question=str(meta.get("question", "") or ""),
            candidate_key=str(meta.get("candidate_key", "") or ""),
            metric=str(meta.get("metric", "") or ""),
            units=str(meta.get("units", "") or ""),
            direction=str(meta.get("direction", "") or ""),
            uncertainty=str(meta.get("uncertainty", "") or ""),
            tags=tags,
            notes=body.strip(),
        )

    @classmethod
    def from_markdown(cls, text: str) -> "PhraseContract":
        """Parse a contract from a markdown string (frontmatter + body)."""
        doc = parse_text(text)
        if not doc.meta:
            raise PhraseContractError(
                "no YAML frontmatter found — a phrase contract needs a '---' block"
            )
        return cls.from_meta(doc.meta, doc.body)

    @classmethod
    def from_file(cls, path: str | Path) -> "PhraseContract":
        """Read and parse a contract markdown file."""
        doc = parse_file(path)
        if not doc.meta:
            raise PhraseContractError(
                f"no YAML frontmatter found in {path} — not a phrase contract"
            )
        return cls.from_meta(doc.meta, doc.body)


# ---------------------------------------------------------------------------
# Default write location
# ---------------------------------------------------------------------------

ENV_CONTRACT_DIR = "MURMURENT_PHRASE_CONTRACT_DIR"


def default_contract_dir() -> Path | None:
    """Where ``murmurent phrase contract new`` writes by default.

    ``$MURMURENT_PHRASE_CONTRACT_DIR`` wins; otherwise a ``phrases/`` folder
    beside the personal Oracle dir (resolved the same way the Oracle is).
    Returns ``None`` when no vault is registered, so the caller can fall back
    to an explicit ``--out`` path or stdout.
    """
    pin = os.environ.get(ENV_CONTRACT_DIR, "").strip()
    if pin:
        return Path(pin).expanduser()
    try:
        from . import oracle_publish as _op  # deferred: optional dashboard deps

        return _op.personal_oracle_dir().parent / "phrases"
    except Exception:
        return None


def default_contract_filename(phrase: str) -> str:
    """The default basename for a contract file, derived from the phrase slug."""
    slug = slugify(phrase) or "phrase"
    return f"{slug}_contract.md"
