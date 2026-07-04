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
