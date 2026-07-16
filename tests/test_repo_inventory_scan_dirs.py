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
