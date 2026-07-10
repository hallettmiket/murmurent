"""
Tests for the murmurent_public → join_requests ingest (Phase 2, increment 2).

All GitHub I/O is injected — no test shells out to `gh`. Covers:
  - issue-form parsing (headings → fields; kind token extraction)
  - ingest creates a local join_request with source_issue + no email
  - dedup: a second run skips issues already ingested (by source_issue)
  - routing: issues for a *different* institution are left untouched
  - member requests are commented + skipped (per-lab flow, not centre)
  - missing required fields → commented, not created, not marked seen
  - no hub configured → JoinIngestError
  - comment_decision_on_issue posts + closes on terminal decisions
  - the decision wiring fires comment-back for source_issue requests
"""

from __future__ import annotations

import pytest

from murmurent.core import join_ingest as JI
from murmurent.core import join_requests as JR
from murmurent.core import centre_init as CI
from murmurent.core import registrar as R


@pytest.fixture
def centre(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL",
                        fake_home / ".murmurent" / "registrar")
    CI.init_centre(
        name="Demo", institution="Demo U", founding_mayor="@tbrowne",
        unique_name="demo",
        public_hub="github.com/acme/murmurent_public#demo",
        write_sentinel=False,
    )
    return tmp_path


def _issue(number, kind="lab — start a new lab (you are the PI)",
           institution="demo", name="my_lab", pi="@api", just="science"):
    body = (
        f"### Institution\n\n{institution}\n\n"
        f"### What are you requesting?\n\n{kind}\n\n"
        f"### Proposed name\n\n{name}\n\n"
        f"### PI / lead handle\n\n{pi}\n\n"
        f"### Justification\n\n{just}\n"
    )
    return {"number": number, "title": "[join]", "body": body,
            "url": f"https://github.com/acme/murmurent_public/issues/{number}",
            "labels": [{"name": "join-request"}]}


class _GH:
    """Records comment/label/close calls; serves a fixed issue list."""
    def __init__(self, issues):
        self.issues = issues
        self.comments = []
        self.labels = []
        self.closed = []
    def fetch(self, repo):
        return list(self.issues)
    def comment(self, repo, number, body):
        self.comments.append((number, body)); return True
    def label(self, repo, number, label):
        self.labels.append((number, label)); return True
    def close(self, repo, number):
        self.closed.append(number); return True


# ---- hub resolution ----------------------------------------------------

def test_hub_repo_parsed_from_public_hub(centre):
    assert JI._hub_repo() == "acme/murmurent_public"


def test_no_hub_raises(centre, monkeypatch):
    CI.update_centre({"public_hub": ""})
    with pytest.raises(JI.JoinIngestError):
        JI.ingest()


# ---- happy path --------------------------------------------------------

def test_ingest_creates_request_with_provenance(centre):
    gh = _GH([_issue(7)])
    created = JI.ingest(fetcher=gh.fetch, commenter=gh.comment, labeler=gh.label)
    assert len(created) == 1
    r = created[0]
    assert r.kind == "lab" and r.proposed_name == "my_lab"
    assert r.proposed_pi == "@api"
    assert r.requester_email == ""                      # public form: no email
    assert r.source_issue == "acme/murmurent_public#7"
    # commented + labelled the issue
    assert any("#0001" in c[1] for c in gh.comments)
    assert (7, JI.INGEST_LABEL) in gh.labels
    # persisted + reloadable with provenance intact
    assert JR.get_request(r.id).source_issue == "acme/murmurent_public#7"


def test_ingest_is_idempotent(centre):
    gh = _GH([_issue(7)])
    JI.ingest(fetcher=gh.fetch, commenter=gh.comment, labeler=gh.label)
    again = JI.ingest(fetcher=gh.fetch, commenter=gh.comment, labeler=gh.label)
    assert again == []                                  # dedup by source_issue
    assert len(JR.iter_requests()) == 1


# ---- routing / filtering ----------------------------------------------

def test_other_institution_left_untouched(centre):
    gh = _GH([_issue(9, institution="otheru")])
    created = JI.ingest(fetcher=gh.fetch, commenter=gh.comment, labeler=gh.label)
    assert created == []
    assert gh.comments == [] and gh.labels == []        # not ours — don't touch


def test_member_request_commented_and_skipped(centre):
    gh = _GH([_issue(11, kind="member — join an existing lab (routed to the PI)")])
    created = JI.ingest(fetcher=gh.fetch, commenter=gh.comment, labeler=gh.label)
    assert created == []
    assert any("lab's PI" in c[1] for c in gh.comments)  # explained
    assert (11, JI.INGEST_LABEL) in gh.labels            # marked seen


def test_missing_required_field_not_created(centre):
    gh = _GH([_issue(12, pi="")])                        # lab with no PI
    created = JI.ingest(fetcher=gh.fetch, commenter=gh.comment, labeler=gh.label)
    assert created == []
    assert any("missing" in c[1].lower() for c in gh.comments)
    # not marked seen — a fixed issue can be reprocessed
    assert (12, JI.INGEST_LABEL) not in gh.labels




# ---- decision → issue comment-back ------------------------------------

def test_comment_decision_declines_and_closes(centre):
    gh = _GH([])
    req = JR.file_request(kind="lab", requester_email="", proposed_name="x",
                          proposed_pi="@p", source_issue="acme/murmurent_public#5")
    req.state = "declined"; req.decline_reason = "out of scope"
    ok = JI.comment_decision_on_issue(req, commenter=gh.comment, closer=gh.close)
    assert ok is True
    assert any("Declined" in c[1] and "out of scope" in c[1] for c in gh.comments)
    assert 5 in gh.closed


def test_comment_decision_approve_no_close(centre):
    gh = _GH([])
    req = JR.file_request(kind="lab", requester_email="", proposed_name="x",
                          proposed_pi="@p", source_issue="acme/murmurent_public#6")
    req.state = "approved"
    JI.comment_decision_on_issue(req, commenter=gh.comment, closer=gh.close)
    assert any("Approved" in c[1] for c in gh.comments)
    assert gh.closed == []                               # approved (non-terminal) stays open


def test_comment_decision_noop_without_source(centre):
    gh = _GH([])
    req = JR.file_request(kind="lab", requester_email="a@b.edu",
                          proposed_name="x", proposed_pi="@p")
    assert JI.comment_decision_on_issue(req, commenter=gh.comment) is False
    assert gh.comments == []
