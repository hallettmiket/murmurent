"""Tests for :mod:`murmurent.core.repo_inventory` scan-dir resolution.

Covers the wiring from the per-host ``scan_dirs`` field (added to the
``Host`` dataclass for absolute + ``$HOME``-relative repo locations)
into the bash snippet that runs over SSH:

  - When a host declares no ``scan_dirs``, the scanner falls back to
    the module-level default (``repo`` + ``repos`` under ``$HOME``).
  - When a host declares ``scan_dirs``, those are used verbatim.
  - The generated bash handles absolute paths (start with ``/``) as-is
    and treats every other entry as ``$HOME``-relative — so a single
    host can mix ``repos`` and ``/srv/projects`` without surprises.

We test at the script-generation level rather than spinning up a real
SSH session: the rest of the inventory pipeline already has the
network call mocked out, and the bash branching is the part most
likely to regress.
"""

from __future__ import annotations

from murmurent.core import hosts, repo_inventory


def test_effective_scan_dirs_falls_back_to_default():
    h = hosts.Host(name="bio", kind="ssh", ssh_host="bio")
    assert repo_inventory._effective_scan_dirs(h) == repo_inventory.DEFAULT_SCAN_DIRS


def test_effective_scan_dirs_uses_host_declaration():
    h = hosts.Host(
        name="bio", kind="ssh", ssh_host="bio",
        scan_dirs=("repos", "/srv/projects"),
    )
    assert repo_inventory._effective_scan_dirs(h) == ("repos", "/srv/projects")


def test_scan_script_quotes_each_entry():
    """Whitespace and shell metachars in scan dirs must be quoted so
    they survive the SSH bash -lc round-trip."""
    script = repo_inventory._scan_script(("repos", "work clones", "/srv/x;rm -rf /"))
    # shlex.quote wraps strings with shell metachars in single quotes.
    assert "'work clones'" in script
    assert "'/srv/x;rm -rf /'" in script
    assert " repos " in script  # safe identifier left unquoted


def test_scan_script_branches_absolute_vs_relative():
    """The generated bash must treat ``/srv/projects`` as absolute and
    ``repos`` as ``$HOME``-relative — same script, different branches."""
    script = repo_inventory._scan_script(("repos", "/srv/projects"))
    # Absolute branch: use $base verbatim.
    assert '/*) full="$base"' in script
    # Relative branch: prepend $HOME.
    assert '*)  full="$HOME/$base"' in script


def test_scan_script_expands_tilde_prefix(tmp_path):
    """A ``~/repos`` entry must resolve to ``$HOME/repos``, not the literal
    ``$HOME/~/repos``. Users type ``~/repos`` naturally (the field placeholder
    even suggested it), and the old ``$HOME/$base`` join turned that into a
    nonexistent path — so the scan silently found zero clones."""
    import subprocess

    home = tmp_path
    repo = home / "repos" / "myproj"
    (repo / ".git").mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)

    for scan_dir in ("~/repos", "~", "repos"):
        script = repo_inventory._scan_script((scan_dir,))
        res = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
        )
        assert str(repo) in res.stdout, (scan_dir, res.stdout, res.stderr)


def test_is_murmurent_infra_repo_classifies_own_repos():
    """murmurent's own repos are flagged so the dashboard never offers a
    'make ready' button for them (#41 pt 5). Project repos are not flagged."""
    f = repo_inventory.is_murmurent_infra_repo
    for infra in ("murmurent", "murmurent_lab_mgmt_mh", "murmurent_vault",
                  "murmurent_public", "murmurent_manuscript",
                  "/home/x/repos/murmurent_lab_mgmt_bio"):
        assert f(infra) is True, infra
    for project in ("dcis_imaging", "my_project", "murmurentish", "", "/x/new_project"):
        assert f(project) is False, project


def test_repo_on_host_to_dict_carries_infra_flag():
    """The JSX repo panel keys the make-ready button off ``is_murmurent_infra``
    in each clone's serialized dict, so the field MUST survive to_dict() for
    both infra and project repos (#55). A missing field reads as falsy in JS and
    re-enables the button — exactly the stale-report failure mode."""
    infra = repo_inventory.RepoOnHost(
        host="local", path="/home/x/repos/murmurent_public", origin_url="",
        has_marker=False, has_claude_dir=False, is_murmurent_ready=False,
        is_murmurent_infra=repo_inventory.is_murmurent_infra_repo(
            "/home/x/repos/murmurent_public"),
    )
    proj = repo_inventory.RepoOnHost(
        host="local", path="/home/x/repos/dcis_imaging", origin_url="",
        has_marker=False, has_claude_dir=False, is_murmurent_ready=False,
        is_murmurent_infra=repo_inventory.is_murmurent_infra_repo(
            "/home/x/repos/dcis_imaging"),
    )
    assert infra.to_dict()["is_murmurent_infra"] is True
    assert proj.to_dict()["is_murmurent_infra"] is False


def test_scan_surfaces_git_worktree_and_plain_folders(tmp_path):
    """The scan must not silently drop folders under a scan dir (#49): a normal
    git repo, a worktree (.git FILE), and a plain non-git folder all appear,
    flagged by is_git; a container folder holding a nested repo is not itself
    emitted (its repo is)."""
    import subprocess
    home = tmp_path
    repos = home / "repos"
    (repos / "proj_git").mkdir(parents=True)
    subprocess.run(["git", "-C", str(repos / "proj_git"), "init", "-q"], check=True)
    (repos / "pin1_screen").mkdir()                       # plain folder
    (repos / "proj_worktree").mkdir()
    (repos / "proj_worktree" / ".git").write_text("gitdir: /x/.git/worktrees/w\n")
    (repos / "group" / "nested").mkdir(parents=True)
    subprocess.run(["git", "-C", str(repos / "group" / "nested"), "init", "-q"], check=True)

    script = repo_inventory._scan_script(("repos",))
    res = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                         env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})
    rows = {}
    for line in res.stdout.splitlines():
        parts = line.split("|")
        rows[parts[0].rsplit("/", 1)[-1]] = parts[-1]  # name -> is_git flag
    assert rows.get("proj_git") == "1"
    assert rows.get("proj_worktree") == "1"              # worktree .git FILE found
    assert rows.get("pin1_screen") == "0"                # plain folder surfaced
    assert rows.get("nested") == "1"
    assert "group" not in rows                           # container not emitted
