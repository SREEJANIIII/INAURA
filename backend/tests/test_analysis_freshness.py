"""Whether a saved analysis still reflects the student's evidence and the current scoring."""
from app.services import evidence_service, skill_engine
from app.services.evidence_service import evidence_fingerprint
from app.api.v1.endpoints.analysis import with_freshness


def _ev(id_, **extra):
    return {"id": id_, "is_excluded": False, "is_ai_assisted": False, **extra}


def test_fingerprint_ignores_order():
    a = evidence_fingerprint([_ev("e1"), _ev("e2")], [_ev("p1")], [])
    b = evidence_fingerprint([_ev("e2"), _ev("e1")], [_ev("p1")], [])
    assert a == b


def test_deleting_or_adding_evidence_changes_the_fingerprint():
    base = evidence_fingerprint([_ev("e1"), _ev("e2")], [_ev("p1")], [_ev("c1")])
    assert evidence_fingerprint([_ev("e1")], [_ev("p1")], [_ev("c1")]) != base
    assert evidence_fingerprint([_ev("e1"), _ev("e2")], [], [_ev("c1")]) != base
    assert evidence_fingerprint([_ev("e1"), _ev("e2"), _ev("e3")], [_ev("p1")], [_ev("c1")]) != base


def test_everything_deleted_differs_from_what_was_analysed():
    assert evidence_fingerprint([], [], []) != evidence_fingerprint([_ev("e1")], [], [])


def test_switching_evidence_off_or_marking_it_ai_assisted_changes_the_fingerprint():
    base = evidence_fingerprint([_ev("e1")], [], [])
    assert evidence_fingerprint([_ev("e1", is_excluded=True)], [], []) != base
    assert evidence_fingerprint([_ev("e1", is_ai_assisted=True)], [], []) != base


def test_flags_stored_in_metadata_count_too():
    in_column = evidence_fingerprint([_ev("e1", is_excluded=True)], [], [])
    in_metadata = evidence_fingerprint([{"id": "e1", "metadata": {"is_excluded": True}}], [], [])
    assert in_column == in_metadata


def test_verification_writes_do_not_change_the_fingerprint():
    # What the analysis itself writes back while it runs
    before = evidence_fingerprint([_ev("e1")], [], [])
    after = evidence_fingerprint(
        [_ev("e1", verification_status="verified", verified_signals=[{"skill": "Python"}], updated_at="later")], [], []
    )
    assert before == after


def _row(fingerprint=None, engine=skill_engine.ENGINE_VERSION):
    return {"id": "a1", "readiness_score": 0.4, "engine_version": engine, "metadata": {"evidence_fingerprint": fingerprint}}


def test_freshness_flags_changed_evidence(monkeypatch):
    monkeypatch.setattr(evidence_service, "current_evidence_fingerprint", lambda user_id: "now")
    assert with_freshness(_row("then"), "u1")["evidence_changed"] is True
    assert with_freshness(_row("now"), "u1")["evidence_changed"] is False


def test_freshness_is_unknown_for_runs_without_a_fingerprint(monkeypatch):
    monkeypatch.setattr(evidence_service, "current_evidence_fingerprint", lambda user_id: "now")
    assert with_freshness(_row(None), "u1")["evidence_changed"] is None


def test_freshness_is_unknown_when_evidence_cant_be_read(monkeypatch):
    monkeypatch.setattr(evidence_service, "current_evidence_fingerprint", lambda user_id: None)
    assert with_freshness(_row("then"), "u1")["evidence_changed"] is None


def test_runs_scored_by_an_older_formula_are_outdated(monkeypatch):
    monkeypatch.setattr(evidence_service, "current_evidence_fingerprint", lambda user_id: "now")
    assert with_freshness(_row("now", engine="4C-v1"), "u1")["scoring_outdated"] is True
    assert with_freshness(_row("now"), "u1")["scoring_outdated"] is False
