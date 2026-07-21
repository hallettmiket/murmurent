"""
Purpose: The compositional choreography object — a posed question that
         contributors answer by offering phrases. A member (the *poser*) states
         the question, the candidate-identity space, and the judging criteria;
         members then attach phrases (:mod:`murmurent.core.phrase_spec`). The
         KEY invariant this module enforces is *joinability*: every contributed
         phrase's output contract must share the choreography's ``candidate_key``
         so the phrases can be aligned + combined later by the judge.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: Keyword args (posing a choreography) or a schema-validated markdown entry
       (YAML frontmatter + optional body).
Output: :class:`Choreography` instances; markdown serialization via
        ``to_markdown()`` / ``from_markdown()`` / ``from_file()``; operations to
        pose, attach a phrase, and ``validate()`` (incl. the candidate-key
        joinability check across all attached phrases).

Boundary: this module defines, poses, and validates the choreography artefact
only. It does NOT run the choreography, invoke the judge, or express results —
those are later phases. See ``docs/choreography.md`` / ``docs/phrases.md``.

Path resolution (for the default write location):
  - ``$MURMURENT_CHOREOGRAPHY_DIR`` if set, else
  - the lab-management repo's ``choreographies/`` folder (choreographies are
    group-shared), else
  - ``<personal-vault>/choreographies/`` (beside the Oracle dir), else
  - ``None`` — the caller falls back to an explicit ``--out`` path or stdout.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import phrase_contract as _pc
from . import phrase_spec as _ps
from .frontmatter import dump_document, parse_file, parse_text

#: Frontmatter fields that must be present and non-empty for a valid object.
REQUIRED_FIELDS: tuple[str, ...] = (
    "question",
    "poser",
    "title",
    "candidate_key",
    "criteria",
)

#: Marker written into the frontmatter so tooling can recognise the artefact.
KIND = "choreography"

slugify = _pc.slugify


class ChoreographyError(ValueError):
    """Raised when a choreography cannot be parsed from markdown."""


@dataclass
class Choreography:
    """A posed compositional question with its attached phrase contributions.

    ``candidate_key`` is the identity space for the whole choreography (same
    vocabulary as :class:`~murmurent.core.phrase_contract.PhraseContract`); it
    is the join column that makes the contributed phrases combinable. ``phrases``
    holds references (path or slug) to the contributed phrase specs.
    """

    question: str
    poser: str
    title: str
    candidate_key: str
    criteria: str
    phrases: list[str] = field(default_factory=list)
    notes: str = ""
    #: Set by :meth:`from_file`; base dir for resolving phrase references.
    source: Path | None = field(default=None, compare=False)

    # -- operations --------------------------------------------------------

    def attach_phrase(self, reference: str) -> bool:
        """Attach a phrase contribution by reference (path or slug).

        Returns ``True`` if newly added, ``False`` if it was already attached
        (idempotent — attaching the same reference twice is a no-op).
        """
        reference = (reference or "").strip()
        if not reference or reference in self.phrases:
            return False
        self.phrases.append(reference)
        return True

    # -- validation --------------------------------------------------------

    def validate(self, base_dir: str | Path | None = None) -> list[str]:
        """Return a list of problems; an empty list means the object is valid.

        Checks:
          - every required field is present and non-empty;
          - ``poser`` is a handle of the form ``@name``;
          - ``candidate_key`` is in the shared vocabulary (or an ``other:``
            escape);
          - **joinability**: each attached phrase resolves to a valid spec whose
            output contract's ``candidate_key`` equals this choreography's
            ``candidate_key``. Any phrase whose contract key differs (or whose
            spec/contract cannot be resolved) is reported.
        """
        problems: list[str] = []

        for name in REQUIRED_FIELDS:
            value = getattr(self, name, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                problems.append(f"missing required field: {name}")

        if self.poser and not self.poser.startswith("@"):
            problems.append(
                f"poser must be a handle of the form '@name' (got {self.poser!r})"
            )

        if self.candidate_key and not _pc.candidate_key_ok(self.candidate_key):
            allowed = ", ".join(sorted(_pc.CANDIDATE_KEY_VOCAB))
            problems.append(
                f"candidate_key {self.candidate_key!r} not in vocabulary "
                f"({allowed}) and not an 'other:<text>' escape"
            )

        problems.extend(self._validate_joinability(base_dir))
        return problems

    def _validate_joinability(self, base_dir: str | Path | None) -> list[str]:
        base = self._resolve_base_dir(base_dir)
        problems: list[str] = []
        for ref in self.phrases:
            spec_path = _ps.resolve_spec_reference(ref, base)
            if spec_path is None:
                problems.append(f"phrase {ref!r}: spec could not be resolved")
                continue
            try:
                spec = _ps.PhraseSpec.from_file(spec_path)
            except _ps.PhraseSpecError as exc:
                problems.append(f"phrase {ref!r}: spec could not be parsed: {exc}")
                continue
            contract = spec.resolved_contract()
            if contract is None:
                problems.append(
                    f"phrase {ref!r}: its output contract could not be resolved"
                )
                continue
            if contract.candidate_key != self.candidate_key:
                problems.append(
                    f"phrase {ref!r}: contract candidate_key "
                    f"{contract.candidate_key!r} does not join the choreography's "
                    f"{self.candidate_key!r} — phrases are not combinable"
                )
        return problems

    def _resolve_base_dir(self, base_dir: str | Path | None) -> Path:
        if base_dir is not None:
            return Path(base_dir).expanduser()
        if self.source is not None:
            return Path(self.source).expanduser().parent
        return Path.cwd()

    def is_valid(self, base_dir: str | Path | None = None) -> bool:
        """Convenience: ``True`` when :meth:`validate` finds no problems."""
        return not self.validate(base_dir)

    # -- serialization -----------------------------------------------------

    def to_frontmatter(self) -> dict[str, Any]:
        """The ordered frontmatter mapping this choreography serializes to."""
        return {
            "kind": KIND,
            "question": self.question,
            "poser": self.poser,
            "title": self.title,
            "candidate_key": self.candidate_key,
            "criteria": self.criteria,
            "phrases": list(self.phrases),
        }

    def to_markdown(self) -> str:
        """Serialize to a markdown entry: YAML frontmatter + optional body."""
        body = self.notes.strip() + "\n" if self.notes.strip() else ""
        return dump_document(self.to_frontmatter(), body)

    @classmethod
    def from_meta(
        cls, meta: dict[str, Any], body: str = "", source: Path | None = None
    ) -> "Choreography":
        """Build a choreography from a parsed frontmatter mapping + body text."""
        if not isinstance(meta, dict):
            raise ChoreographyError("choreography frontmatter must be a mapping")
        phrases_raw = meta.get("phrases") or []
        if isinstance(phrases_raw, str):
            phrases = [p.strip() for p in phrases_raw.split(",") if p.strip()]
        else:
            phrases = [str(p) for p in phrases_raw]
        return cls(
            question=str(meta.get("question", "") or ""),
            poser=str(meta.get("poser", "") or ""),
            title=str(meta.get("title", "") or ""),
            candidate_key=str(meta.get("candidate_key", "") or ""),
            criteria=str(meta.get("criteria", "") or ""),
            phrases=phrases,
            notes=body.strip(),
            source=source,
        )

    @classmethod
    def from_markdown(cls, text: str) -> "Choreography":
        """Parse a choreography from a markdown string (frontmatter + body)."""
        doc = parse_text(text)
        if not doc.meta:
            raise ChoreographyError(
                "no YAML frontmatter found — a choreography needs a '---' block"
            )
        return cls.from_meta(doc.meta, doc.body)

    @classmethod
    def from_file(cls, path: str | Path) -> "Choreography":
        """Read + parse a choreography file (records ``source`` for resolution)."""
        p = Path(path)
        doc = parse_file(p)
        if not doc.meta:
            raise ChoreographyError(
                f"no YAML frontmatter found in {path} — not a choreography"
            )
        return cls.from_meta(doc.meta, doc.body, source=p)


# ---------------------------------------------------------------------------
# Pose (create) helper
# ---------------------------------------------------------------------------


def pose(
    *,
    question: str,
    poser: str,
    title: str,
    candidate_key: str,
    criteria: str,
) -> Choreography:
    """Pose a new choreography (no phrases attached yet)."""
    return Choreography(
        question=question,
        poser=poser,
        title=title,
        candidate_key=candidate_key,
        criteria=criteria,
    )


# ---------------------------------------------------------------------------
# Default write location
# ---------------------------------------------------------------------------

ENV_CHOREOGRAPHY_DIR = "MURMURENT_CHOREOGRAPHY_DIR"


def default_choreography_dir() -> Path | None:
    """Where ``murmurent choreography new`` writes by default.

    ``$MURMURENT_CHOREOGRAPHY_DIR`` wins; otherwise, because choreographies are
    group-shared, a ``choreographies/`` folder in the lab-management repo if one
    resolves; failing that a ``choreographies/`` folder beside the personal
    Oracle dir. Returns ``None`` when neither resolves, so the caller can fall
    back to an explicit ``--out`` path or stdout.
    """
    pin = os.environ.get(ENV_CHOREOGRAPHY_DIR, "").strip()
    if pin:
        return Path(pin).expanduser()
    # Group-shared: prefer the lab-mgmt repo when it is resolvable on disk.
    try:
        from .repo import lab_mgmt_repo_root  # deferred: optional in some envs

        root = lab_mgmt_repo_root()
        if root and root.exists():
            return root / "choreographies"
    except Exception:
        pass
    # Fall back to the personal vault (beside the Oracle dir).
    try:
        from . import oracle_publish as _op  # deferred: optional dashboard deps

        return _op.personal_oracle_dir().parent / "choreographies"
    except Exception:
        return None


def default_choreography_filename(question: str) -> str:
    """The default basename for a choreography file, from the question slug."""
    slug = slugify(question) or "choreography"
    return f"{slug}.md"
