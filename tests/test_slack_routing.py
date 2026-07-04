"""Once a centre is live with a private mayor channel, wigamig system
notifications must default THERE (mayor-only), not the shared dev channel.
Verifies the _route/_default_channel redirect in slack_notify."""

from __future__ import annotations

from wigamig.dashboard import slack_notify as SN


class _Centre:
    def __init__(self, mayor_channel_id=""):
        self.mayor_channel_id = mayor_channel_id


def test_route_redirects_default_to_mayor_channel(monkeypatch):
    monkeypatch.setattr("wigamig.core.centre_init.read_centre",
                        lambda *a, **k: _Centre("CMAYOR123"))
    # the dev fallback and an empty channel both go to the private mayor channel
    assert SN._route(SN._CHAN_DEFAULT) == "CMAYOR123"
    assert SN._route("") == "CMAYOR123"
    # an explicit per-group channel id is left alone
    assert SN._route("CLABCHAN99") == "CLABCHAN99"


def test_route_falls_back_to_dev_when_no_mayor_channel(monkeypatch):
    # no centre at all
    monkeypatch.setattr("wigamig.core.centre_init.read_centre", lambda *a, **k: None)
    assert SN._route(SN._CHAN_DEFAULT) == SN._CHAN_DEFAULT
    # centre exists but hasn't run centre-slack-setup (no mayor channel yet)
    monkeypatch.setattr("wigamig.core.centre_init.read_centre",
                        lambda *a, **k: _Centre(""))
    assert SN._route(SN._CHAN_DEFAULT) == SN._CHAN_DEFAULT


def test_route_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("lab_info unreadable")
    monkeypatch.setattr("wigamig.core.centre_init.read_centre", boom)
    # routing must degrade to the dev channel, never propagate the error
    assert SN._route(SN._CHAN_DEFAULT) == SN._CHAN_DEFAULT


# ---- post_message_result surfaces failures (no more silent swallow) -------

def test_post_message_result_no_token(monkeypatch):
    monkeypatch.setattr(SN, "_token", lambda: None)
    res = SN.post_message_result("C0X", "hi")
    assert res.ok is False and res.error == "no_token" and res.detail


def test_post_message_result_maps_slack_error(monkeypatch):
    monkeypatch.setattr(SN, "_token", lambda: "xoxb-x")
    monkeypatch.setattr("wigamig.core.centre_init.read_centre", lambda *a, **k: None)

    class _R:
        def json(self):
            return {"ok": False, "error": "channel_not_found"}
    monkeypatch.setattr("httpx.post", lambda *a, **k: _R())
    res = SN.post_message_result("C0MISSING", "hi")
    assert res.ok is False and res.error == "channel_not_found"
    assert "workspace" in res.detail.lower()     # actionable hint, not just the code


def test_post_message_result_ok(monkeypatch):
    monkeypatch.setattr(SN, "_token", lambda: "xoxb-x")
    monkeypatch.setattr("wigamig.core.centre_init.read_centre", lambda *a, **k: None)

    class _R:
        def __init__(self, d): self._d = d
        def json(self): return self._d
    posts = {"post": _R({"ok": True, "ts": "123.45"})}
    monkeypatch.setattr("httpx.post", lambda *a, **k: posts["post"])
    monkeypatch.setattr("httpx.get",
                        lambda *a, **k: _R({"ok": True, "permalink": "https://slack/x"}))
    res = SN.post_message_result("C0OK", "hi")
    assert res.ok is True and res.link == "https://slack/x"
