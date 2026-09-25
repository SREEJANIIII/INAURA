import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import type { AvailableAssessment } from "../services/assessment";
import AssessmentModal from "../components/assessment/AssessmentModal";
import SkillAssessmentLayers from "../components/assessment/SkillAssessmentLayers";
import DsaChecklist from "../components/assessment/DsaChecklist";
import Button from "../components/ui/app-button";
import { CodeforcesPanel, DsaCoverage } from "../components/analysis/CodingPractice";
import { codingPracticeData } from "../components/analysis/codingPracticeData";
import { assessmentsData, dsaChecklistData, evidencePageData, resultsPageData, subscribePageData } from "../lib/pageData";
import "./AnalysisResults.css";
import "../components/analysis/AnalysisPage.css";

type View = "skills" | "dsa";

/**
 * Skill Assessment: proving what you know, so INAURA stops having to take your word for it.
 *
 * Two views — the skills your analysis suggests proving, and the DSA checklist. Neither needs
 * an analysis to open: the checklist stands on its own, and the skills list says what to do
 * when there's nothing to prove yet. Every result flows back into the analysis, so the
 * readiness and gaps on Career Track move when a check is passed.
 */
export default function SkillAssessment({ view }: { view: View }) {
  const assessable = useSyncExternalStore(subscribePageData, assessmentsData.peek);
  const evidence = useSyncExternalStore(subscribePageData, evidencePageData.peek);
  const [active, setActive] = useState<AvailableAssessment | null>(null);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [view]);

  useEffect(() => {
    assessmentsData.fetch().catch(() => undefined);
    evidencePageData.fetch().catch(() => undefined);
  }, []);

  // A finished check changes the analysis, so everything built from it is re-read
  const refresh = useCallback(() => {
    resultsPageData.fetch(true).catch(() => {
      // No analysis yet: the suggestions still need refreshing on their own
      assessmentsData.fetch(true).catch(() => undefined);
    });
    dsaChecklistData.fetch(true).catch(() => undefined);
  }, []);

  const coding = useMemo(() => codingPracticeData(evidence?.evidence ?? []), [evidence]);

  return (
    <div className="an">
      <div className="an__inner">
        <nav className="sa-tabs" aria-label="Skill assessment">
          <Link to="/skill-assessment" className={view === "skills" ? "is-active" : undefined} aria-current={view === "skills" ? "page" : undefined}>
            Skills you know
          </Link>
          <Link to="/skill-assessment/dsa" className={view === "dsa" ? "is-active" : undefined} aria-current={view === "dsa" ? "page" : undefined}>
            DSA
          </Link>
        </nav>

        {view === "skills" ? (
          <>
            <section className="an-sec an-overview" aria-labelledby="h-assess">
              <div className="an-overview__head">
                <div>
                  <h1 id="h-assess" className="an-overview__title">Skills you know</h1>
                  <p className="an-overview__sub">
                    Show INAURA what you can actually do. Every check you finish sharpens your skill gaps and your roadmap.
                  </p>
                </div>
                <Button asChild variant="secondary"><Link to="/analysis">Update evidence</Link></Button>
              </div>

              {!assessable ? (
                <div aria-busy="true">
                  <div className="an-skel an-skel--block" />
                  <p className="an-visually-hidden">Loading the skills you can prove</p>
                </div>
              ) : assessable.length > 0 ? (
                <SkillAssessmentLayers items={assessable} onStartKnowledge={setActive} onCompleted={refresh} />
              ) : (
                <>
                  <p className="an-empty">
                    There’s nothing to prove yet. Add your evidence and run your analysis — INAURA then suggests the skills worth
                    proving, starting with the ones you’ve claimed but haven’t shown.
                  </p>
                  <div className="an-actions">
                    <Button asChild variant="primary"><Link to="/analysis">Add evidence</Link></Button>
                    <Button asChild variant="secondary"><Link to="/skill-assessment/dsa">Practise DSA meanwhile</Link></Button>
                  </div>
                </>
              )}
            </section>

            {coding.cfInspection && (
              <section className="an-sec" aria-labelledby="h-cf">
                <header className="an-sec__head">
                  <h2 id="h-cf">Codeforces performance</h2>
                  <p>Verified from your Codeforces profile — it counts as evidence on its own, so there’s nothing to take here.</p>
                </header>
                <CodeforcesPanel data={coding} />
              </section>
            )}
          </>
        ) : (
          <>
            <DsaChecklist onProgressUpdate={refresh} />

            {coding.hasDsa && (
              <section className="an-sec" aria-labelledby="h-lc-coverage">
                <header className="an-sec__head">
                  <h2 id="h-lc-coverage">Your LeetCode profile</h2>
                  <p>What your verified LeetCode profile shows about the patterns you’ve practised.</p>
                </header>
                <DsaCoverage data={coding} />
              </section>
            )}
          </>
        )}
      </div>

      {active && (
        <AssessmentModal
          key={active.skill}
          skill={active.skill}
          evidenceProficiency={active.proficiency}
          evidenceConfidence={active.confidence}
          onClose={() => setActive(null)}
          onCompleted={refresh}
        />
      )}
    </div>
  );
}
