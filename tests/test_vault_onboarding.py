"""Tests for the onboarding hook that offers `murmurent vault init` during
`murmurent init` (issue #25 onboarding scope). Every seam is injected so no real
`gh` auth / `gh repo create` / network / real-home write happens.
"""

from __future__ import annotations

from murmurent.commands import init_cmd as IC


def _echo_collector():
    lines: list[str] = []
    return lines, (lambda *a: lines.append(" ".join(str(x) for x in a)))


def test_offer_vault_declined_is_noop():
    lines, echo = _echo_collector()
    called = {"init": 0}

    out = IC._offer_vault_init(
        "allie",
        confirm=lambda *a, **k: False,          # member says no
        prompt=lambda *a, **k: "/should/not/ask",
        echo=echo,
        gh_auth=lambda: True,
        initializer=lambda **k: called.__setitem__("init", called["init"] + 1),
    )
    assert out["status"] == "declined"
    assert called["init"] == 0                   # never touched provisioning
    assert any("vault init" in ln for ln in lines)   # printed the run-later hint


def test_offer_vault_no_gh_auth_degrades():
    lines, echo = _echo_collector()
    called = {"init": 0}

    out = IC._offer_vault_init(
        "allie",
        confirm=lambda *a, **k: pytest_fail_if_called(),
        prompt=lambda *a, **k: "x",
        echo=echo,
        gh_auth=lambda: False,                   # gh not authed
        initializer=lambda **k: called.__setitem__("init", called["init"] + 1),
    )
    assert out["status"] == "no_gh_auth"
    assert called["init"] == 0
    assert any("gh" in ln.lower() for ln in lines)


def pytest_fail_if_called(*_a, **_k):
    raise AssertionError("confirm() must not be called when gh auth is absent")


def test_offer_vault_accepted_provisions_with_fake_seam(tmp_path, monkeypatch):
    """Member accepts → the injected initializer runs; onboarding reports success.
    Uses a FAKE initializer — no real gh repo create."""
    from murmurent.dashboard import machine_settings as MS
    monkeypatch.setattr(MS, "MACHINE_FILE", tmp_path / "home" / "machine.yaml")
    lines, echo = _echo_collector()
    seen = {}

    def fake_initializer(*, path):
        seen["path"] = path
        return {"ok": True, "repo": "allie/murmurent_vault", "path": path,
                "pushed": True}

    out = IC._offer_vault_init(
        "allie",
        confirm=lambda *a, **k: True,
        prompt=lambda *a, **k: str(tmp_path / "myvault"),
        echo=echo,
        gh_auth=lambda: True,
        initializer=fake_initializer,
    )
    assert out["status"] == "created"
    assert seen["path"] == str(tmp_path / "myvault")
    assert any("personal vault ready" in ln for ln in lines)


def test_offer_vault_accepted_end_to_end_with_fake_gh(tmp_path, monkeypatch):
    """Accept path wired through the REAL init_personal_vault, but with fake
    repo_creator/cloner/syncer so nothing hits GitHub — proves the vault is
    scaffolded + machine.yaml pinned via the onboarding entry point."""
    from murmurent.core import vault_provision as VP
    from murmurent.core.vault_sync import CommitResult
    from murmurent.dashboard import machine_settings as MS
    monkeypatch.setattr(MS, "MACHINE_FILE", tmp_path / "home" / "machine.yaml")

    dest = tmp_path / "vault"

    def real_init(*, path):
        return VP.init_personal_vault(
            path=path, owner="allie",
            repo_creator=lambda o, n: (True, "created"),
            cloner=lambda o, n, d: (Path_mkdir(d), (True, "cloned"))[1],
            syncer=lambda p, *, message: CommitResult(True, True, True, "pushed"),
        )

    lines, echo = _echo_collector()
    out = IC._offer_vault_init(
        "allie",
        confirm=lambda *a, **k: True,
        prompt=lambda *a, **k: str(dest),
        echo=echo,
        gh_auth=lambda: True,
        initializer=real_init,
    )
    assert out["status"] == "created"
    assert (dest / "oracle" / "drafts").is_dir()
    assert (dest / "CLAUDE.md").exists()
    assert MS.load().obsidian_vault_path == str(dest)


def test_offer_vault_initializer_error_never_crashes(tmp_path):
    lines, echo = _echo_collector()

    def boom(**k):
        raise RuntimeError("offline")

    out = IC._offer_vault_init(
        "allie",
        confirm=lambda *a, **k: True,
        prompt=lambda *a, **k: str(tmp_path / "v"),
        echo=echo,
        gh_auth=lambda: True,
        initializer=boom,
    )
    assert out["status"] == "error" and "offline" in out["detail"]
    assert any("vault init" in ln for ln in lines)   # run-later hint printed


def Path_mkdir(d):
    from pathlib import Path
    Path(d).mkdir(parents=True, exist_ok=True)
    return True
