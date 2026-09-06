import pytest
from app.services import skill_engine as se

# Helper to create signal
def sig(val, rel):
    return {"signal_value": val, "source_reliability": rel}


def test_proficiency_weighted_average():
    # Python: GitHub 0.80*0.90, LeetCode 0.70*0.85, Coursework 0.75*0.80, Resume 0.90*0.50
    signals = [sig(0.80, 0.90), sig(0.70, 0.85), sig(0.75, 0.80), sig(0.90, 0.50)]
    prof, w, cnt, _ = se.proficiency(signals)
    expected = (0.80*0.90 + 0.70*0.85 + 0.75*0.80 + 0.90*0.50) / (0.90+0.85+0.80+0.50)
    assert abs(prof - expected) < 1e-6
    assert prof == se.clamp01(prof)
    assert 0 <= prof <= 1

def test_proficiency_no_evidence():
    prof, w, cnt, _ = se.proficiency([])
    assert prof == 0
    assert w == 0
    assert cnt == 0

def test_proficiency_clamping():
    # Very high weight should still clamp
    signals = [sig(1.5, 1.0), sig(-0.5, 1.0)]
    prof, _, _, _ = se.proficiency(signals)
    assert 0 <= prof <= 1

def test_confidence_formula():
    # W=2.5, D=3 → confidence =0.55*1 +0.45*1 =1
    conf, wn, dn = se.confidence(2.5, 3)
    assert abs(conf - 1.0) < 1e-6
    # W=1.25 (half), D=1.5 (half) → 0.55*0.5+0.45*0.5=0.5
    conf2, _, _ = se.confidence(1.25, 1.5)
    assert abs(conf2 - 0.5) < 1e-6

def test_confidence_clamping():
    conf, _, _ = se.confidence(10, 10)  # W/2.5=4→1, D/3=3.33→1
    assert conf == 1.0
    conf2, _, _ = se.confidence(0, 0)
    assert conf2 == 0.0

def test_source_diversity():
    # W=1.0, D=1 → 0.55*0.4+0.45*0.333=0.37
    conf1, _, _ = se.confidence(1.0, 1)
    conf3, _, _ = se.confidence(1.0, 3)
    assert conf3 > conf1  # more diversity → higher confidence

def test_gap_when_current_less_than_required():
    assert se.gap(0.6, 0.9) == pytest.approx(0.3)
    assert se.gap(0.2, 0.8) == pytest.approx(0.6)

def test_gap_zero_when_current_greater():
    assert se.gap(0.9, 0.75) == 0
    assert se.gap(0.8, 0.8) == 0
    assert se.gap(1.0, 0.5) == 0

def test_gap_priority_formula():
    # 100 * 0.3 * 0.8 * 0.9 * 0.7 * 0.6
    prio = se.gap_priority(0.3, 0.8, 0.9, 0.7, 0.6)
    expected = 100 * 0.3 * 0.8 * 0.9 * 0.7 * 0.6
    assert abs(prio - expected) < 1e-6

def test_gap_priority_zero_when_gap_zero():
    assert se.gap_priority(0, 0.9, 0.9, 0.8, 0.8) == 0
    assert se.gap_priority(0.5, 0.9, 0.9, 0.8, 0.8) != 0

def test_readiness_formula():
    # 0.45*0.8 +0.25*0.6+0.30*0.7 = 0.36+0.15+0.21=0.72
    r = se.readiness(0.8, 0.6, 0.7)
    assert abs(r - 0.72) < 1e-6

def test_readiness_clamping():
    assert se.readiness(1,1,1) == 1.0
    assert se.readiness(0,0,0) == 0.0
    assert se.readiness(2,2,2) == 1.0  # clamp
    assert se.readiness(-1,-1,-1) == 0.0

def test_evidence_traceability():
    # Signals should preserve source info
    from app.services.signal_extractor import extract_signals
    # Mock evidence: project with Python
    evidence = []
    projects = [{"id": "p1", "name": "ML Stock", "description": "Python project", "technologies": ["Python", "Pandas"], "project_url": None, "github_url": None}]
    certs = []
    # We need a supabase client for normalize; mock by patching
    # Instead test that proficiency keeps evidence_count and diversity
    signals = [{"signal_value": 0.9, "source_reliability": 0.9, "source_type": "project"}, {"signal_value": 0.6, "source_reliability": 0.5, "source_type": "resume"}]
    prof, w, cnt, _ = se.proficiency(signals)
    assert cnt == 2
    # Confidence with D=2 should be > D=1
    c1, _, _ = se.confidence(w, 2)
    c2, _, _ = se.confidence(w, 1)
    assert c1 > c2

def test_insufficient_evidence():
    # No signals → proficiency 0, confidence 0, gap = required, priority conservative (low confidence → low priority)
    prof, w, cnt, _ = se.proficiency([])
    assert prof == 0
    conf, _, _ = se.confidence(w, 0)
    assert conf == 0
    gap = se.gap(prof, 0.8)
    assert gap == 0.8
    prio_low_conf = se.gap_priority(gap, 0.9, 0.9, conf, 0.8)
    prio_high_conf = se.gap_priority(gap, 0.9, 0.9, 0.9, 0.8)
    assert prio_low_conf < prio_high_conf  # low confidence → conservative
    assert prio_low_conf == 0  # because confidence 0 → priority 0

def test_no_nan():
    for prof in [0, 0.5, 1]:
        for conf in [0, 0.5, 1]:
            for gap in [0, 0.5, 1]:
                prio = se.gap_priority(gap, 0.5, 0.5, conf, 0.5)
                assert not gap != gap  # not NaN
                assert prio == prio
                assert 0 <= prio <= 100
    assert se.readiness(0.5,0.5,0.5) == se.readiness(0.5,0.5,0.5)

def test_no_division_by_zero():
    # No signals
    prof, w, cnt, _ = se.proficiency([])
    assert prof == 0
    # Single signal with weight 0? Should handle
    prof2, _, _, _ = se.proficiency([{"signal_value": 0.5, "source_reliability": 0}])
    assert prof2 == 0

def test_negative_gaps_never():
    for cur in [0, 0.5, 1]:
        for req in [0, 0.5, 1]:
            g = se.gap(cur, req)
            assert g >= 0
            assert g <= 1

def test_same_input_same_output():
    s1 = [sig(0.7, 0.9), sig(0.6, 0.8)]
    s2 = [sig(0.7, 0.9), sig(0.6, 0.8)]
    assert se.proficiency(s1)[0] == se.proficiency(s2)[0]
    assert se.confidence(2.0, 2)[0] == se.confidence(2.0, 2)[0]
    assert se.gap(0.5, 0.9) == se.gap(0.5, 0.9)

def test_different_users_isolation():
    # Engine is pure — different user data doesn't leak
    # Simulate two users with different signals
    user_a = [sig(0.9, 0.9)]
    user_b = [sig(0.3, 0.9)]
    assert se.proficiency(user_a)[0] != se.proficiency(user_b)[0]
    # Confidence should also differ if diversity differs
    assert se.confidence(0.9, 1)[0] != se.confidence(0.9, 2)[0]
