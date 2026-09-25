"""
Purpose: Start a new choreography from nothing, in one action: create its
         repository, make it murmurent-ready, declare it a choreography, pose
         its question, make the first commit, and ask the PI to make it a
         project. Shared by ``murmurent choreography init`` and the dashboard's
         Choreographies panel, so the two cannot drift apart.
Author: Mike Hallett (with Claude Code)
Date: 2026-09-24
Input: a :class:`ChoreographyPlan` (what the person answered) and the acting
       member's handle.
Output: an :class:`InitResult`: one :class:`~murmurent.core.preflight.Probe`
        per step, the paths written, the request number, and the steps that
        are still the person's to do.

Why this exists: creating a choreography used to be ten separate steps across
git, the CLI, a hand-edited YAML file and the dashboard, and no page listed
them all. Everything here reuses an existing path rather than re-implementing
it: readiness is :func:`core.adopt.adopt_clone`, the question is
:class:`core.choreography.Choreography`, and the project is an ordinary
project-create request naming this repository. Approving that request is what
creates the private GitHub repository, the Slack channel and the lead card, so
this module does none of those itself.

What it cannot do, and says so in ``next_steps``: approve the project (the PI
decides), write a contributor's contract or pipeline, or run the judge.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import choreography as _ch
from . import contribution_contract as _pc
from . import repo as _repo
from . import repo_ready as _rr
from .preflight import Probe

#: The two modes a choreography runs in. See docs/choreography.md.
MODES: tuple[str, ...] = ("compositional", "coordination")

#: A repository name: lowercase snake_case, starting with a letter.
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: The agents a compositional choreography uses unless told otherwise.
DEFAULT_AGENTS: tuple[str, ...] = (
    "blacksmith", "adversary", "bookworm", "artist", "judge")

#: Folders every lab project has (rules/project-structure.md), plus the
#: decision log a choreography ships as evidence for its method.
LAYOUT_DIRS: tuple[str, ...] = ("exp", "src", "obsolete", "data", "decisions")

#: Where the question is written when no group location resolves.
IN_REPO_QUESTION_DIR = "choreography"


class InitError(ValueError):
    """The plan cannot be carried out. ``problems`` lists every reason."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class ChoreographyPlan:
    """Everything a person decides when starting a choreography.

    The question fields are optional: leave ``candidate_key`` blank to create
    the repository now and pose the question later with
    ``murmurent choreography new``.
    """

    name: str
    title: str
    summary: str
    mode: str = "compositional"
    approaches: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=lambda: list(DEFAULT_AGENTS))
    lab: str = ""
    # The posed question (compositional mode).
    question: str = ""          # slug; defaults to the repository name
    candidate_key: str = ""
    criteria: str = ""
    # The project.
    request_project: bool = True
    members: list[str] = field(default_factory=list)
    sensitivity: str = "standard"

    @property
    def question_slug(self) -> str:
        return _pc.slugify(self.question or self.name).replace("-", "_")

    @property
    def poses_question(self) -> bool:
        return bool(self.candidate_key.strip())

    def problems(self) -> list[str]:
        """Every reason this plan cannot run, found before anything is written."""
        out: list[str] = []
        if not _NAME_RE.match(self.name or ""):
            out.append(
                f"name {self.name!r} must be lowercase letters, digits and "
                "underscores, starting with a letter (for example pin1_inhibition)")
        else:
            from .repo_inventory import is_murmurent_infra_repo
            if is_murmurent_infra_repo(self.name):
                out.append(f"{self.name!r} is reserved for murmurent's own repositories")
        if not self.title.strip():
            out.append("a title is required")
        if not self.summary.strip():
            out.append("a summary is required")
        if self.mode not in MODES:
            out.append(f"mode must be one of {', '.join(MODES)} (got {self.mode!r})")
        if self.poses_question:
            if not _pc.candidate_key_ok(self.candidate_key.strip()):
                allowed = ", ".join(sorted(_pc.CANDIDATE_KEY_VOCAB))
                out.append(f"candidate key {self.candidate_key!r} must be one of "
                           f"{allowed}, or other:<description>")
            if not self.criteria.strip():
                out.append("posing the question needs criteria for the judge")
        elif self.criteria.strip():
            out.append("criteria were given without a candidate key; give both, "
                       "or neither to pose the question later")
        if self.sensitivity not in ("standard", "restricted", "clinical"):
            out.append("sensitivity must be standard, restricted or clinical")
        return out

    def declaration(self) -> dict:
        """The ``kind: choreography`` fields added to ``.murmurent.yaml``."""
        decl: dict = {
            "kind": _ch.KIND,
            "name": self.name,
            "title": self.title.strip(),
            "summary": " ".join(self.summary.split()),
            "mode": self.mode,
        }
        if self.approaches:
            decl["approaches"] = list(self.approaches)
        # No ``agents`` here: readiness owns that field and it already means
        # "the agents this repo uses", which is what `choreography install`
        # reads. :func:`_step_ready` records them there.
        decl["data"] = {"root_subdir": self.name}
        if self.poses_question:
            decl["question"] = self.question_slug
        from .. import __version__
        decl["requires"] = {"murmurent": f">={__version__}"}
        return decl


@dataclass
class InitResult:
    """What :func:`init_choreography` did, step by step."""

    repo_path: Path
    probes: list[Probe] = field(default_factory=list)
    question_path: Path | None = None
    request_id: int | None = None
    next_steps: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(p.status == "fail" and p.required for p in self.probes)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "repo_path": str(self.repo_path),
            "question_path": str(self.question_path) if self.question_path else None,
            "request_id": self.request_id,
            "probes": [p.to_dict() for p in self.probes],
            "next_steps": list(self.next_steps),
        }


# ---------------------------------------------------------------------------
# The one entry point
# ---------------------------------------------------------------------------


def init_choreography(plan: ChoreographyPlan, *, actor: str = "") -> InitResult:
    """Create the choreography ``plan`` describes. See this module's header.

    Raises :class:`InitError` before touching the disk when the plan is
    invalid. After that, each step reports a probe; a failed required step
    stops the run, and a failed optional one (the data folders, the commit,
    the project request) is reported and the run carries on.
    """
    problems = plan.problems()
    repo_path = _repo.repos_root() / plan.name
    existing = _rr.read_marker(repo_path)
    if existing and existing.get("kind") == _ch.KIND:
        problems.append(f"{repo_path} is already a choreography")
    if problems:
        raise InitError(problems)

    result = InitResult(repo_path=repo_path)
    written: list[Path] = []

    for step in (_step_folder, _step_git, _step_ready, _step_declare):
        probe = step(plan, repo_path, written)
        result.probes.append(probe)
        if probe.status == "fail" and probe.required:
            return result

    if plan.poses_question:
        probe, result.question_path = _step_question(plan, repo_path, actor, written)
        result.probes.append(probe)
    result.probes.append(_step_data_folders(plan))
    result.probes.append(_step_commit(repo_path, written))
    if plan.request_project:
        probe, result.request_id = _step_request(plan, actor)
        result.probes.append(probe)

    result.next_steps = _next_steps(plan, result)
    return result


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _write_if_absent(path: Path, text: str, written: list[Path]) -> None:
    """Write a starter file, never replacing one the person already has."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    written.append(path)


def _step_folder(plan: ChoreographyPlan, repo_path: Path,
                 written: list[Path]) -> Probe:
    reused = repo_path.is_dir()
    try:
        repo_path.mkdir(parents=True, exist_ok=True)
        for d in LAYOUT_DIRS:
            (repo_path / d).mkdir(exist_ok=True)
        # git does not track empty folders; a placeholder keeps the layout.
        for d in ("exp", "obsolete", "data"):
            if not any((repo_path / d).iterdir()):
                _write_if_absent(repo_path / d / ".gitkeep", "", written)
        _write_if_absent(repo_path / "README.md", _readme(plan), written)
        _write_if_absent(repo_path / "decisions" / "README.md", _DECISIONS_README, written)
        _write_if_absent(repo_path / "how_this_project_breaks.md", _FAILURES, written)
        _write_if_absent(repo_path / "src" / "ready_to_delete.md", _READY_TO_DELETE, written)
    except OSError as exc:
        return Probe(name="folder", status="fail", detail=str(exc), required=True)
    how = "used the existing folder" if reused else "created"
    return Probe(name="folder", status="ok", required=True,
                 detail=f"{how} {repo_path} with {', '.join(LAYOUT_DIRS)}")


def _step_git(plan: ChoreographyPlan, repo_path: Path,
              written: list[Path]) -> Probe:
    if (repo_path / ".git").exists():
        return Probe(name="git", status="ok", required=True,
                     detail="already tracked by git")
    proc = subprocess.run(["git", "init", "-q", "-b", "main", str(repo_path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return Probe(name="git", status="fail", required=True,
                     detail=(proc.stderr or proc.stdout).strip())
    return Probe(name="git", status="ok", required=True,
                 detail="started tracking with git (branch main)")


def _step_ready(plan: ChoreographyPlan, repo_path: Path,
                written: list[Path]) -> Probe:
    from . import adopt as _adopt
    try:
        outcome = _adopt.adopt_clone(clone_path=str(repo_path), lab=plan.lab,
                                     agents=list(plan.agents))
    except _adopt.AdoptError as exc:
        return Probe(name="murmurent-ready", status="fail", required=True,
                     detail=str(exc))
    written.extend(p for p in (repo_path / _rr.MARKER_FILENAME,
                               repo_path / "CLAUDE.md") if p.exists())
    # An agent the commons lacks is linked as a warning, not a failure. Say so
    # now rather than let someone find out mid-run.
    absent = [p.name.split(":", 1)[1].strip() for p in outcome.probes
              if p.name.startswith("cc_agent:") and p.status != "ok"]
    if absent:
        return Probe(name="murmurent-ready", status="warn", required=True,
                     detail="ready, but this machine has no agent named "
                            f"{', '.join(absent)}; check the spelling, or install it")
    return Probe(name="murmurent-ready", status="ok", required=True,
                 detail="wrote .murmurent.yaml, so the patient-data check runs here")


def _step_declare(plan: ChoreographyPlan, repo_path: Path,
                  written: list[Path]) -> Probe:
    try:
        _rr.update_marker(repo_path, plan.declaration())
    except (OSError, ValueError) as exc:
        return Probe(name="declaration", status="fail", required=True,
                     detail=str(exc))
    return Probe(name="declaration", status="ok", required=True,
                 detail=f"declared kind: choreography ({plan.mode}) in .murmurent.yaml")


def _step_question(plan: ChoreographyPlan, repo_path: Path, actor: str,
                   written: list[Path]) -> tuple[Probe, Path | None]:
    poser = f"@{actor.lstrip('@')}" if actor else ""
    obj = _ch.Choreography(
        question=plan.question_slug, poser=poser, title=plan.title.strip(),
        candidate_key=plan.candidate_key.strip(), criteria=plan.criteria.strip(),
        repo=plan.name,
    )
    problems = obj.validate()
    if problems:
        return Probe(name="question", status="warn",
                     detail="not posed: " + "; ".join(problems)), None
    # The group location is where the dashboard shows it and where members
    # attach contributions. Without one, the repository keeps it.
    group_dir = _ch.default_choreography_dir()
    base = Path(group_dir) if group_dir else repo_path / IN_REPO_QUESTION_DIR
    dest = base / _ch.default_choreography_filename(plan.question_slug)
    if dest.exists():
        return Probe(name="question", status="warn",
                     detail=f"not posed: {dest} already exists"), None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(obj.to_markdown(), encoding="utf-8")
    except OSError as exc:
        return Probe(name="question", status="warn", detail=f"not posed: {exc}"), None
    if not group_dir:
        written.append(dest)
    where = "the group's choreographies folder" if group_dir else "this repository"
    return Probe(name="question", status="ok",
                 detail=f"posed in {where}: {dest}"), dest


def _step_data_folders(plan: ChoreographyPlan) -> Probe:
    from . import lab_vm as _lv
    root = _lv.data_root()
    if not root.is_dir():
        return Probe(name="data folders", status="warn",
                     detail=f"no data root on this machine ({root}); create "
                            f"immutable/{plan.name} and append_only/{plan.name} "
                            "on the machine that holds the data")
    made = []
    try:
        for d in (_lv.project_immutable_dir(plan.name),
                  _lv.project_append_only_dir(plan.name)):
            d.mkdir(parents=True, exist_ok=True)
            made.append(str(d))
    except OSError as exc:
        return Probe(name="data folders", status="warn", detail=str(exc))
    return Probe(name="data folders", status="ok", detail=", ".join(made))


def _step_commit(repo_path: Path, written: list[Path]) -> Probe:
    paths = [str(p.relative_to(repo_path)) for p in written
             if p.exists() and repo_path in p.parents]
    if not paths:
        return Probe(name="first commit", status="ok", detail="nothing new to commit")
    add = subprocess.run(["git", "-C", str(repo_path), "add", "--", *paths],
                         capture_output=True, text=True)
    commit = add if add.returncode != 0 else subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-q", "-m",
         "Start the choreography\n\nCreated by `murmurent choreography init`."],
        capture_output=True, text=True)
    if commit.returncode != 0:
        why = (commit.stderr or commit.stdout).strip().splitlines()
        return Probe(name="first commit", status="warn",
                     detail=f"not committed ({why[-1] if why else 'git failed'}); "
                            f"run: git -C {repo_path} add -A && "
                            f"git -C {repo_path} commit -m 'Start the choreography'")
    return Probe(name="first commit", status="ok",
                 detail=f"committed {len(paths)} starter file(s)")


def _step_request(plan: ChoreographyPlan, actor: str) -> tuple[Probe, int | None]:
    if not actor:
        return Probe(name="project request", status="warn",
                     detail="no member identity on this machine, so no request was "
                            "filed; use ＋ new project on the dashboard"), None
    from ..dashboard import request_actions as _ra
    try:
        filed = _ra.file_create_request(
            actor=actor, project=plan.name, proposed_members=list(plan.members),
            sensitivity=plan.sensitivity,
            justification=f"Choreography: {plan.title.strip()}",
            attach_repos=[plan.name],
        )
    except _ra.RequestActionError as exc:
        return Probe(name="project request", status="warn",
                     detail=f"not filed: {exc}"), None
    try:
        from ..dashboard import slack_notify as _notify
        _notify.project_request(kind="project", project=plan.name, actor=actor)
    except Exception:  # noqa: BLE001 — a missed Slack note never undoes a request
        pass
    req = filed.request
    return Probe(name="project request", status="ok",
                 detail=f"filed request #{req.id} for the PI to approve"), req.id


# ---------------------------------------------------------------------------
# What is left for the person
# ---------------------------------------------------------------------------


def _next_steps(plan: ChoreographyPlan, result: InitResult) -> list[str]:
    steps: list[str] = []
    if result.request_id is not None:
        steps.append(
            f"Your PI approves request #{result.request_id} on the dashboard. "
            "Approval creates the private GitHub repository, the project's Slack "
            "channel and your lead card, which arrives as a Slack message. Then run "
            "`murmurent import-card bundle.json` and issue each member's card from "
            "the project's Members list.")
    else:
        steps.append(
            "To make it a project, use ＋ new project on the dashboard and pick "
            f"the repository {plan.name}. Approval creates the GitHub copy.")
    if plan.mode != "compositional":
        steps.append("Write the recipe in README.md: who does what, in what order, "
                     "and what each step produces.")
        return steps
    q = plan.question_slug
    qfile = str(result.question_path) if result.question_path else f"{q}.md"
    if result.question_path is None:
        steps.append(
            "Pose the question: `murmurent choreography new --question "
            f"{q} --poser @you --title \"...\" --candidate-key <key> "
            "--criteria @criteria.md`")
    steps.append(
        "Each contributor describes their approach with "
        f"`murmurent contribution contract new --question {q} ...` and "
        "`murmurent contribution spec new --question " + q + " ...`, then states "
        "it to the group from the dashboard's contributions panel.")
    steps.append(
        f"Each contributor writes their results table under "
        f"append_only/{plan.name}/<contribution>/ and sets `output:` in their spec.")
    steps.append(
        "Attach each contribution with the dashboard's attach button, or "
        f"`murmurent choreography offer {qfile} --contribution <slug>`. Then check "
        f"they line up with `murmurent choreography validate {qfile}`.")
    steps.append(
        f"Run it: `murmurent choreography prepare-run {qfile}`, ask the judge agent "
        "to combine the run package and the adversary to review the result, then "
        f"`murmurent choreography freeze-run {qfile} --result <judge output>`.")
    return steps


# ---------------------------------------------------------------------------
# Starter files
# ---------------------------------------------------------------------------


def _readme(plan: ChoreographyPlan) -> str:
    approaches = "".join(f"- `{a}`\n" for a in plan.approaches) or "- (none named yet)\n"
    return f"""# {plan.title.strip()}

{" ".join(plan.summary.split())}

This is a murmurent **choreography**: a recipe for how several people, and the
agents they run, work together on one question. It runs in **{plan.mode}**
mode. Its description is in `.murmurent.yaml`.

## Approaches

{approaches}
## Layout

| Folder | What goes in it |
|---|---|
| `exp/` | one numbered folder per experiment, e.g. `00_first_look` |
| `src/` | code shared across experiments |
| `obsolete/` | code no longer used but not yet deleted |
| `data/` | small files only; data lives under the data root in `{plan.name}/` |
| `decisions/` | one dated file per decision (see `decisions/README.md`) |

`how_this_project_breaks.md` records every defect found and how it was caught.
The decision records and that file are published with the choreography, because
they are the evidence for its method.
"""


_DECISIONS_README = """# Decisions

One file per decision, named `<YYYY-MM-DD>_<slug>.md`. Each one says what was
decided, who decided it, on what evidence, and what it replaces. When the
evidence changes, write a new decision that withdraws the old one rather than
editing it, so the record shows what was believed and when.

These records are published with the choreography.
"""

_FAILURES = """# How this project breaks

Every defect found in this choreography, and how it was caught. Add an entry
when something goes wrong, even when it is fixed the same day.

| Date | What broke | How it was caught | What changed |
|---|---|---|---|
"""

_READY_TO_DELETE = """# Ready to delete

Files under the data root for this project that are out of date or superseded,
and can be deleted. List a file here when a newer version replaces it or when
it moves to `obsolete/`.
"""
