"""
Purpose: Provision a member's **personal** Obsidian vault as a private GitHub
         repo (``murmurent_vault``) — create the repo, scaffold the standard
         Tier-II folders + a vault-root ``CLAUDE.md``, clone it to this machine,
         and pin the clone path in ``machine.yaml``.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-16
Input: the person's GitHub login (resolved via ``gh api user`` unless passed),
       an optional ``--path`` clone override, injectable ``repo_creator`` /
       ``cloner`` / ``syncer`` seams (so tests never touch real GitHub).
Output: a structured dict summarising each step (mirrors ``cert_provision``).

Issue #25, Part B (§2). This is the ONE genuinely new repo in Part B: the lab
(group) vault is the existing lab-mgmt repo, already provisioned + synced. The
seams follow ``core.cert_provision``'s shape exactly so the test suite injects
fakes and no ``gh repo create`` / real clone ever runs under test.

Back-compat (memo §2): if the target clone already exists as a git repo with a
DIFFERENT remote, refuse rather than clobber; a matching (or absent) remote is
adopted in place. The clone is also refused inside ``$MURMURENT_DATA_ROOT``
(raw/refined hook territory).
"""

from __future__ import annotations

from pathlib import Path

from . import lab_vm as _lab_vm
from . import repo as _repo

# Standard Tier-II layout scaffolded into a fresh personal vault. ``oracle`` and
# ``lab-notebook`` are the murmurent-managed tiers (resolved by the oracle MCP);
# ``maps-legends`` holds the vault's own taxonomy that agents consult before
# writing (issue #25 §5). ``oracle/drafts`` is where publish-to-lab candidates
# sit before ``murmurent oracle publish`` promotes them. ``murmurent_data``
# holds arbitrary reference files (PDFs, spreadsheets, protocols, images) that
# agents Glob/Read on demand — resolved by the murmurent-data MCP.
VAULT_SUBDIRS: tuple[str, ...] = (
    "oracle", "oracle/drafts", "lab-notebook", "maps-legends", "murmurent_data")

GITKEEP = ".gitkeep"
CLAUDE_MD = "CLAUDE.md"


class VaultProvisionError(RuntimeError):
    """A personal-vault provisioning step could not be completed."""


# ---------------------------------------------------------------------------
# Seed content
# ---------------------------------------------------------------------------


def seed_claude_md() -> str:
    """Vault-root ``CLAUDE.md`` seeded into a fresh personal vault (issue #25 §5.1).

    CC's standard CLAUDE.md discovery walk picks this up when a session opens a
    file *inside* the vault. Agents that start OUTSIDE the vault (in a project
    repo) instead consult ``murmurent vault paths`` — pointed to here so both
    entry points agree.
    """
    return (
        "# Personal murmurent vault\n\n"
        "This is your **personal** murmurent vault (`murmurent_vault`, a private "
        "repo on your own GitHub). It holds your Tier-II knowledge across every "
        "project.\n\n"
        "## Layout\n\n"
        "- `oracle/` — your personal Oracle entries (schema: "
        "`rules/oracle_schema.md`). murmurent-managed; searched by the oracle MCP "
        "(`personal` tier).\n"
        "- `oracle/drafts/` — publish-to-lab candidates; promote with "
        "`murmurent oracle publish <slug>`.\n"
        "- `lab-notebook/` — your daily lab-notebook entries (oracle MCP "
        "`notebook` tier).\n"
        "- `maps-legends/` — this vault's own taxonomy (maps of content, tag "
        "legends). **Read this before writing a new entry** so tags + structure "
        "stay consistent.\n"
        "- `murmurent_data/` — arbitrary reference files (PDFs, spreadsheets, "
        "protocols, images) that agents may read on demand; not schema-validated "
        "like the Oracle.\n\n"
        "## Sync\n\n"
        "This vault is git-backed. After writing entries, run `murmurent vault "
        "sync` to commit + push (best-effort). Pull the latest from another "
        "machine with `murmurent vault info` / the dashboard's Personal-Oracle "
        "**update** button.\n\n"
        "## Agents\n\n"
        "Any agent (oracle, bookworm, lab_oracle, …) can resolve this vault's "
        "location, the `maps-legends/` folder, and the `murmurent_data/` folder "
        "— for both the personal and lab vaults — by running `murmurent vault "
        "paths` (prints JSON). The lab (group) vault is the lab-mgmt repo; its "
        "`oracle/`, `lab-notebook/`, `maps-legends/`, and `murmurent_data/` live "
        "there.\n"
    )


# ---------------------------------------------------------------------------
# Default (real) seams — never exercised under test; tests inject fakes.
# ---------------------------------------------------------------------------


def gh_auth_ready() -> bool:
    """True when ``gh`` is installed AND authenticated. The onboarding prompt
    guards on this: creating the vault repo needs a working ``gh auth``, so when
    it's absent we point the member at ``murmurent vault init`` for later rather
    than failing onboarding."""
    import shutil
    import subprocess
    if shutil.which("gh") is None:
        return False
    try:
        return subprocess.run(["gh", "auth", "status"],
                              capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _default_owner_resolver() -> str | None:
    """The current user's GitHub login (``gh api user``), or ``None``."""
    from . import identity as _id
    ident = _id.from_gh()
    return ident.handle if ident is not None else None


def _default_repo_creator(owner: str, name: str) -> tuple[bool, str]:
    """Create private ``owner/name`` if missing. Tolerant of "already exists".
    Returns ``(ok, detail)`` — mirrors ``cert_provision._default_repo_creator``."""
    from . import project_provision as _pp
    if not _pp._gh_available():
        return (False, "gh CLI not installed")
    if _pp._gh(["repo", "view", f"{owner}/{name}"]).returncode == 0:
        return (True, "exists")
    res = _pp._gh(["repo", "create", f"{owner}/{name}", "--private"])
    if res.returncode == 0:
        return (True, "created")
    return (False, (res.stderr or res.stdout or "").strip() or "gh repo create failed")


def _default_cloner(owner: str, name: str, dest: Path) -> tuple[bool, str]:
    """Clone ``owner/name`` into ``dest`` (creating parents). ``(ok, detail)``."""
    from . import project_provision as _pp
    if not _pp._gh_available():
        return (False, "gh CLI not installed")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    res = _pp._gh(["repo", "clone", f"{owner}/{name}", str(dest)])
    return (res.returncode == 0, (res.stderr or res.stdout or "").strip() or "cloned")


def _default_adopt_pusher(dest: Path, owner: str, name: str,
                          *, message: str) -> tuple[bool, bool, str]:
    """Turn an existing dir into a git repo and push it to a NEW private
    ``owner/name`` via gh. Returns ``(ok, pushed, detail)`` — best-effort push:
    ``ok`` reflects the local commit, ``pushed`` the remote push (a network
    failure keeps ``ok=True``). The caller has ALREADY written the .gitignore
    that excludes sensitivity-tagged files, so `git add -A` never stages them."""
    import subprocess
    from . import project_provision as _pp

    dest = Path(dest)

    def _git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(dest), *args],
                              capture_output=True, text=True, timeout=120)

    if not _pp._gh_available():
        return (False, False, "gh CLI not installed")
    if not (dest / ".git").exists():
        r = _git("init", "-b", "main")
        if r.returncode != 0:
            return (False, False, (r.stderr or "git init failed").strip())
    _install_precommit_guard(dest)
    _git("add", "-A")
    c = _git("commit", "-m", message)
    if c.returncode != 0 and "nothing to commit" not in (c.stdout + c.stderr):
        return (False, False, (c.stderr or c.stdout or "git commit failed").strip()[:300])
    # Create the private repo FROM this local repo and push it in one gh call
    # (handles auth via gh's git credential helper).
    res = _pp._gh(["repo", "create", f"{owner}/{name}", "--private",
                   "--source", str(dest), "--remote", "origin", "--push"])
    if res.returncode == 0:
        return (True, True, "created private repo + pushed")
    return (True, False, "committed locally; gh repo create/push failed: "
            + (res.stderr or res.stdout or "").strip()[:300])


# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------


def scaffold_vault(root: Path) -> list[str]:
    """Create the standard subfolders (+ ``.gitkeep``) and a vault-root
    ``CLAUDE.md`` under ``root`` if absent. Idempotent — only writes what's
    missing; never overwrites an existing ``CLAUDE.md`` (so a user's edits and
    an adopted vault's own file are preserved). Returns the relative paths
    created."""
    root = Path(root)
    created: list[str] = []
    for sub in VAULT_SUBDIRS:
        d = root / sub
        if not d.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            created.append(sub + "/")
        keep = d / GITKEEP
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
            created.append(f"{sub}/{GITKEEP}")
    claude = root / CLAUDE_MD
    if not claude.exists():
        claude.write_text(seed_claude_md(), encoding="utf-8")
        created.append(CLAUDE_MD)
    return created


# ---------------------------------------------------------------------------
# Adopting an EXISTING vault — keep sensitivity-tagged files off GitHub
# ---------------------------------------------------------------------------

# Machine-local / non-content cruft that should never ride into the vault repo.
_VAULT_GITIGNORE_CRUFT: tuple[str, ...] = (
    ".obsidian/workspace*",
    ".obsidian/cache",
    ".trash/",
    ".DS_Store",
    "*.tmp",
)

# Sensitivities that, by default, are kept OUT of the GitHub-backed vault. The
# personal vault is a private repo, but "private on GitHub" is still egress to a
# third party — clinical/PHI-tagged notes stay local unless the owner overrides.
DEFAULT_EXCLUDED_SENSITIVITIES: tuple[str, ...] = ("clinical",)

# The ONLY top-level folders a murmurent-scoped vault tracks. An existing
# Obsidian vault usually holds far more (health/, journal/, recipes/, …); the
# default adopt scope is "murmurent" — an ALLOWLIST that tracks just these +
# CLAUDE.md and leaves everything else local (off GitHub). This is safer than a
# clinical denylist, which would push untagged personal notes.
MURMURENT_TRACKED_FOLDERS: tuple[str, ...] = (
    "oracle", "lab-notebook", "maps-legends", "murmurent_data")


def _allowlist_gitignore_lines() -> list[str]:
    """.gitignore that tracks ONLY the murmurent folders + CLAUDE.md; everything
    else in the vault stays local. The ``/*`` ignore is top-level only, so a
    re-included folder's contents are tracked once git descends into it."""
    lines = [
        "# murmurent vault — ALLOWLIST scope: only murmurent Tier-II folders are",
        "# tracked on GitHub. Everything else in this Obsidian vault stays LOCAL.",
        "# Re-run `murmurent vault init --adopt` to regenerate.",
        "",
        "/*",
        "!/.gitignore",
        "!/.gitattributes",
        "!/CLAUDE.md",
    ]
    lines += [f"!/{d}/" for d in MURMURENT_TRACKED_FOLDERS]
    return lines


def scan_sensitive(vault_root: Path,
                   *, sensitivities: tuple[str, ...] = DEFAULT_EXCLUDED_SENSITIVITIES,
                   ) -> list[str]:
    """Relative paths of ``.md`` files whose frontmatter ``sensitivity`` is in
    ``sensitivities`` (default: clinical). Read-only; tolerant of unparseable
    files (skipped). Content is NOT returned — only paths — so a caller can
    show the exclusion list without surfacing PHI."""
    from .frontmatter import parse_file as _pf
    root = Path(vault_root)
    want = {s.strip().lower() for s in sensitivities}
    hits: list[str] = []
    for p in root.rglob("*.md"):
        if ".git" in p.parts:
            continue
        try:
            meta = _pf(p).meta or {}
        except Exception:  # noqa: BLE001 — an unreadable note just isn't scanned
            continue
        if str(meta.get("sensitivity") or "").strip().lower() in want:
            hits.append(str(p.relative_to(root)))
    return sorted(hits)


def _vault_gitignore_lines(excluded_rel: list[str]) -> list[str]:
    """The .gitignore body for a vault: machine-local cruft + each
    sensitivity-tagged file anchored to the repo root."""
    lines = [
        "# murmurent vault — machine-local + sensitivity-tagged files kept off GitHub.",
        "# Regenerate the sensitivity block with `murmurent vault init --adopt`.",
        "",
        *(_VAULT_GITIGNORE_CRUFT),
    ]
    if excluded_rel:
        lines += ["", "# Sensitivity-tagged (e.g. clinical) — never pushed:"]
        # Anchor with a leading slash so only the exact file is ignored (not a
        # same-named file elsewhere). git-ignore treats '#' and trailing space
        # specially — escape them.
        for rel in excluded_rel:
            esc = rel.replace("#", "\\#")
            if esc != esc.rstrip():
                esc = esc.rstrip() + "\\ " * (len(esc) - len(esc.rstrip()))
            lines.append("/" + esc)
    return lines


def plan_adopt(vault_root: Path,
               *, scope: str = "murmurent",
               sensitivities: tuple[str, ...] = DEFAULT_EXCLUDED_SENSITIVITIES,
               ) -> dict:
    """Dry-run preview of adopting ``vault_root``. Pure — creates nothing, pushes
    nothing. This is what a caller shows the user before any push.

    ``scope="murmurent"`` (default, safest): ALLOWLIST — only the murmurent
    folders are tracked; every other folder stays local. ``scope="all"``: the
    whole vault minus sensitivity-tagged files (a denylist)."""
    root = Path(vault_root)
    all_md = [str(p.relative_to(root)) for p in root.rglob("*.md")
              if ".git" not in p.parts]
    top = lambda rel: rel.split("/", 1)[0]  # noqa: E731

    if scope == "murmurent":
        # Everything the allowlist re-includes (tracked); everything else local.
        allowlisted = set(MURMURENT_TRACKED_FOLDERS) | {
            "CLAUDE.md", ".gitignore", ".gitattributes"}
        tracked = [f for f in all_md
                   if top(f) in MURMURENT_TRACKED_FOLDERS or f in allowlisted]
        local = sorted({top(f) for f in all_md if top(f) not in allowlisted})
        return {
            "vault": str(root), "exists": root.is_dir(),
            "is_git": (root / ".git").exists(), "scope": "murmurent",
            "tracked_folders": list(MURMURENT_TRACKED_FOLDERS),
            "tracked_md": len(tracked),
            "kept_local_folders": local,     # top-level names only — no content
            "total_md": len(all_md),
            "gitignore": _allowlist_gitignore_lines(),
        }

    excluded = scan_sensitive(root, sensitivities=sensitivities)
    return {
        "vault": str(root), "exists": root.is_dir(),
        "is_git": (root / ".git").exists(), "scope": "all",
        "excluded_sensitivities": list(sensitivities),
        "excluded_files": excluded,          # paths only — no content
        "excluded_count": len(excluded),
        "total_md": len(all_md),
        "tracked_md_estimate": len(all_md) - len(excluded),
        "gitignore": _vault_gitignore_lines(excluded),
    }


def _install_precommit_guard(dest: Path) -> bool:
    """Install a git pre-commit hook that REFUSES to commit any staged file
    tagged ``sensitivity: clinical`` — an ongoing safety net so a clinical note
    added later can't slip into the GitHub-backed vault even if .gitignore
    misses it. Returns True if written."""
    hooks = Path(dest) / ".git" / "hooks"
    if not hooks.is_dir():
        return False
    hook = hooks / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        "# murmurent vault guard: block committing clinical-tagged notes.\n"
        "staged=$(git diff --cached --name-only --diff-filter=ACM | grep '\\.md$' || true)\n"
        "bad=''\n"
        "for f in $staged; do\n"
        "  if [ -f \"$f\" ] && grep -qiE '^sensitivity:[[:space:]]*clinical' \"$f\"; then\n"
        "    bad=\"$bad\\n  $f\"\n"
        "  fi\n"
        "done\n"
        "if [ -n \"$bad\" ]; then\n"
        "  printf 'murmurent vault: refusing to commit clinical-tagged file(s):%b\\n' \"$bad\"\n"
        "  printf 'These stay local. Add them to .gitignore or drop the sensitivity tag.\\n'\n"
        "  exit 1\n"
        "fi\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    return True


# ---------------------------------------------------------------------------
# Remote inspection (for the adopt / refuse decision)
# ---------------------------------------------------------------------------


def _remote_owner_name(git_dir: Path) -> str | None:
    """``owner/name`` of ``git_dir``'s ``origin`` remote, lower-cased, or ``None``.

    Normalises the three remote-URL shapes murmurent clones use
    (``git@host:owner/name.git``, ``https://host/owner/name(.git)``,
    ``ssh://git@host/owner/name``). ``None`` when there is no origin remote — an
    adoptable state (a local-only git vault the user is wiring up)."""
    import subprocess
    try:
        res = subprocess.run(
            ["git", "-C", str(git_dir), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    url = (res.stdout or "").strip()
    if not url:
        return None
    url = url.removesuffix(".git")
    if url.startswith("git@") and ":" in url:
        tail = url.split(":", 1)[1]
    else:
        # strip scheme + host: keep the last two path segments
        tail = url.split("://", 1)[-1]
        segs = [s for s in tail.split("/") if s]
        tail = "/".join(segs[-2:]) if len(segs) >= 2 else tail
    tail = tail.strip("/").lower()
    return tail or None


def _under_lab_vm(dest: Path, env: dict | None = None) -> bool:
    """True when ``dest`` would land inside ``$MURMURENT_DATA_ROOT`` — the
    raw/refined hook territory a vault must never occupy."""
    try:
        vm = _lab_vm.lab_vm_root(env).expanduser().resolve()
        return Path(dest).expanduser().resolve().is_relative_to(vm)
    except (OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Personal-vault init
# ---------------------------------------------------------------------------


def _pin_machine_vault_path(dest: Path) -> bool:
    """Pin ``obsidian_vault_path=dest`` in ``machine.yaml`` (preserving the rest
    of the settings). Best-effort — returns whether the pin was written."""
    try:
        from ..dashboard import machine_settings as _ms
        s = _ms.load()
        _ms.write(s.model_copy(update={"obsidian_vault_path": str(dest)}))
        return True
    except Exception:  # noqa: BLE001 — pinning is best-effort; the clone still landed
        return False


def init_personal_vault(
    *,
    path: str | Path | None = None,
    owner: str | None = None,
    env: dict | None = None,
    repo_creator=None,
    cloner=None,
    owner_resolver=None,
    syncer=None,
    adopt_pusher=None,
    adopt: bool = False,
    adopt_scope: str = "murmurent",
    sensitivities: tuple[str, ...] = DEFAULT_EXCLUDED_SENSITIVITIES,
    commit: bool = True,
) -> dict:
    """Provision this member's personal vault (``murmurent_vault``).

    Steps: resolve the GitHub owner → decide the clone path (``--path`` else
    ``core.repo.personal_vault_path()``) → refuse if it lands inside the lab-VM
    root → adopt an existing matching clone or create+clone a fresh one →
    scaffold the Tier-II folders + ``CLAUDE.md`` → best-effort commit+push →
    pin the path in ``machine.yaml``.

    ``repo_creator`` / ``cloner`` / ``owner_resolver`` / ``syncer`` are
    injectable seams (default to the real ``gh`` calls + ``vault_sync``); tests
    inject fakes so no real GitHub repo is created or cloned. Returns a
    structured summary; failure modes come back as ``{"ok": False, "error": …}``
    rather than raising (except an unresolvable owner-less call)."""
    name = _repo.personal_vault_repo_name()
    owner_resolver = owner_resolver or _default_owner_resolver
    repo_creator = repo_creator or _default_repo_creator
    cloner = cloner or _default_cloner
    if syncer is None:
        from . import vault_sync as _vs
        syncer = _vs.commit_and_push

    owner = (owner or "").lstrip("@").strip() or (owner_resolver() or "")
    if not owner:
        return {"ok": False, "error": "no_github_owner",
                "detail": "could not resolve your GitHub login (run `gh auth login` "
                          "or pass --owner)", "repo": None, "path": None}
    expected = f"{owner}/{name}"

    dest = Path(path).expanduser() if path else _repo.personal_vault_path()
    if _under_lab_vm(dest, env):
        return {"ok": False, "error": "inside_lab_vm", "repo": expected, "path": str(dest),
                "detail": f"refusing to place the vault inside $MURMURENT_DATA_ROOT "
                          f"({_lab_vm.data_root(env)}) — that is immutable/append_only "
                          f"hook territory. Choose a --path outside it."}

    created_repo = False
    adopted = False
    cloned = False

    if dest.exists():
        is_git = (dest / ".git").exists()
        if is_git:
            remote = _remote_owner_name(dest)
            if remote and remote != expected.lower():
                return {"ok": False, "error": "different_remote", "repo": expected,
                        "path": str(dest), "remote": remote,
                        "detail": f"{dest} is already a git repo whose origin is "
                                  f"{remote!r}, not {expected!r}. Refusing to clobber it "
                                  f"— clone the vault to a different --path, or point "
                                  f"machine.yaml at this repo if it IS your vault."}
            adopted = True  # matching remote, or a local-only git vault
        else:
            try:
                nonempty = any(dest.iterdir())
            except OSError:
                nonempty = True
            if nonempty and not adopt:
                return {"ok": False, "error": "exists_not_git", "repo": expected,
                        "path": str(dest),
                        "detail": f"{dest} exists and is not empty but is not a git "
                                  f"repo. To back this existing vault on GitHub, re-run "
                                  f"with --adopt (sensitivity-tagged notes are excluded); "
                                  f"or choose an empty --path for a fresh vault."}
            if nonempty and adopt:
                # Adopt an EXISTING (non-git) Obsidian vault. Order is
                # PHI-critical: write .gitignore BEFORE any `git add`, so
                # excluded notes never enter git history / GitHub. Then
                # scaffold + git-init + push.
                #   scope="murmurent" (default): ALLOWLIST — only oracle/,
                #     lab-notebook/, maps-legends/ + CLAUDE.md are tracked;
                #     every other folder in the vault stays local.
                #   scope="all": whole vault minus sensitivity-tagged files.
                if adopt_scope == "murmurent":
                    gi_lines = _allowlist_gitignore_lines()
                    excluded = scan_sensitive(dest, sensitivities=sensitivities)
                else:
                    excluded = scan_sensitive(dest, sensitivities=sensitivities)
                    gi_lines = _vault_gitignore_lines(excluded)
                (dest / ".gitignore").write_text(
                    "\n".join(gi_lines) + "\n", encoding="utf-8")
                scaffolded = scaffold_vault(dest)
                pusher = adopt_pusher or _default_adopt_pusher
                ok, detail, pushed = pusher(dest, owner, name, message=(
                    "vault: adopt existing Obsidian vault as murmurent personal vault "
                    f"(scope={adopt_scope}; excluded content kept off GitHub via .gitignore)"))
                if not ok:
                    return {"ok": False, "error": "adopt_failed", "repo": expected,
                            "path": str(dest), "detail": detail, "scope": adopt_scope}
                pinned = _pin_machine_vault_path(dest)
                return {"ok": True, "repo": expected, "owner": owner, "path": str(dest),
                        "created_repo": True, "adopted": True, "cloned": False,
                        "scope": adopt_scope, "clinical_excluded": excluded,
                        "scaffolded": scaffolded, "committed": True, "pushed": pushed,
                        "pinned": pinned, "sync_detail": detail}
            # empty dir → safe to create+clone into it below

    if not adopted:
        ok, detail = repo_creator(owner, name)
        if not ok:
            return {"ok": False, "error": "repo_create_failed", "repo": expected,
                    "path": str(dest), "detail": detail}
        created_repo = detail != "exists"
        ok, detail = cloner(owner, name, dest)
        if not ok:
            return {"ok": False, "error": "clone_failed", "repo": expected,
                    "path": str(dest), "detail": detail}
        cloned = True

    scaffolded = scaffold_vault(dest)

    committed = pushed = False
    sync_detail = "skipped"
    if commit:
        res = syncer(dest, message=(
            "vault: scaffold murmurent personal vault "
            "(oracle/, oracle/drafts/, lab-notebook/, maps-legends/, "
            "murmurent_data/, CLAUDE.md)"))
        committed = getattr(res, "committed", False)
        pushed = getattr(res, "pushed", False)
        sync_detail = getattr(res, "detail", "")

    pinned = _pin_machine_vault_path(dest)

    return {"ok": True, "repo": expected, "owner": owner, "path": str(dest),
            "created_repo": created_repo, "adopted": adopted, "cloned": cloned,
            "scaffolded": scaffolded, "committed": committed, "pushed": pushed,
            "pinned": pinned, "sync_detail": sync_detail}


def init_lab_vault(*, env: dict | None = None) -> dict:
    """Convenience: ensure the Tier-II subfolders exist under the EXISTING
    lab-mgmt clone (the lab/group vault). Does NOT create a second repo — the
    lab vault IS ``murmurent_lab_mgmt_<lab>`` (memo §0/§2). Reports
    ``no_lab_mgmt_clone`` when the clone isn't on this machine yet."""
    root = _repo.lab_mgmt_repo_root()
    if not root.is_dir():
        return {"ok": False, "error": "no_lab_mgmt_clone", "path": str(root),
                "detail": f"no lab-mgmt clone at {root} — clone it per docs/lab_mgmt.md "
                          f"first (the lab vault is the lab-mgmt repo)."}
    created: list[str] = []
    for sub in ("oracle", "oracle/drafts", "lab-notebook", "maps-legends",
                "murmurent_data"):
        d = root / sub
        if not d.is_dir():
            d.mkdir(parents=True, exist_ok=True)
            created.append(sub + "/")
        keep = d / GITKEEP
        if not any(p for p in d.iterdir() if p.name != GITKEEP) and not keep.exists():
            keep.write_text("", encoding="utf-8")
            created.append(f"{sub}/{GITKEEP}")
    return {"ok": True, "path": str(root), "created": created,
            "detail": "the lab vault is the lab-mgmt repo; scaffolded missing subfolders "
                      "only (no repo created)"}


# ---------------------------------------------------------------------------
# Path resolver (for `murmurent vault paths`)
# ---------------------------------------------------------------------------


def resolve_vault_paths() -> dict:
    """Resolve both vault roots + their Tier-II subfolders for agents whose
    session starts OUTSIDE a vault (issue #25 §5.2). Returns JSON-serialisable
    dicts; a ``null`` root means "not registered / not cloned on this machine".

    Personal subfolders honour the per-machine ``oracle_subfolder`` /
    ``notebook_subfolder`` from ``machine.yaml``; the lab vault uses the fixed
    lab-mgmt convention (``oracle/``, ``lab-notebook/``, ``maps-legends/``).
    """
    from . import vault_sync as _vs

    oracle_sub, notebook_sub = "oracle", "lab-notebook"
    try:
        from ..dashboard import machine_settings as _ms
        s = _ms.load()
        oracle_sub = s.oracle_subfolder or oracle_sub
        notebook_sub = s.notebook_subfolder or notebook_sub
    except Exception:  # noqa: BLE001
        pass

    personal = _vs.personal_vault_root()
    if personal is not None:
        personal_block = {
            "root": str(personal),
            "oracle": str(personal / oracle_sub),
            "notebook": str(personal / notebook_sub),
            "maps_legends": str(personal / "maps-legends"),
            "murmurent_data": str(personal / "murmurent_data"),
        }
    else:
        personal_block = {"root": None, "oracle": None, "notebook": None,
                          "maps_legends": None, "murmurent_data": None}

    lab = _repo.lab_mgmt_repo_root()
    lab_block = {
        "root": str(lab),
        "oracle": str(lab / "oracle"),
        "notebook": str(lab / "lab-notebook"),
        "maps_legends": str(lab / "maps-legends"),
        "murmurent_data": str(lab / "murmurent_data"),
        "exists": lab.is_dir(),
    }
    return {"personal": personal_block, "lab": lab_block}


__all__ = [
    "VaultProvisionError", "VAULT_SUBDIRS", "seed_claude_md", "scaffold_vault",
    "init_personal_vault", "init_lab_vault", "resolve_vault_paths",
]
