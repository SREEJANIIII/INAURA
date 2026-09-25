import { useState, useSyncExternalStore, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { ANALYSIS_SECTION_IDS, getActiveSection, subscribeActiveSection } from "../../lib/sectionSpy";
import { analysisStateData, evidencePageData, resultsPageData, subscribePageData } from "../../lib/pageData";
import { freshness, staleLabel } from "../../lib/analysisFreshness";
import "./Sidebar.css";

type NavItem = { label: string; to: string; icon?: ReactNode; children?: NavItem[]; soon?: boolean };

const Icon = ({ children }: { children: ReactNode }) => (
  <svg className="sidebar__icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
);

const items: NavItem[] = [
  {
    label: "Career Track",
    to: "/career-track",
    icon: <Icon><path d="M5 21V4" /><path d="M5 4.5h11.5l-2.2 3.5 2.2 3.5H5" /><circle cx="18.5" cy="18.5" r="2" /><path d="M8.5 18.5h8" /></Icon>,
  },
  {
    label: "Evidence",
    to: "/analysis",
    icon: <Icon><path d="M7 3.5h7l4 4v13H7z" /><path d="M14 3.5v4h4" /><path d="M10 12.5h5M10 16h5" /></Icon>,
  },
  {
    label: "Analysis",
    to: "/analysis/results",
    icon: <Icon><path d="M4 20.5h16" /><rect x="5.5" y="11" width="3" height="6.5" rx="1" /><rect x="10.5" y="6.5" width="3" height="11" rx="1" /><rect x="15.5" y="13.5" width="3" height="4" rx="1" /></Icon>,
    children: [
      // Named as the results page names its own sections, so the sidebar and the page agree
      { label: "Priority Gaps", to: "/analysis/results#priority-gaps" },
      { label: "Evidence Gaps", to: "/analysis/results#evidence-gaps" },
      { label: "Skill Quadrants", to: "/analysis/results#skill-quadrants" },
      { label: "Skill Overview", to: "/analysis/results#skill-overview" },
      { label: "Evidence Sources", to: "/analysis/results#evidence-sources" },
    ],
  },
  {
    label: "Skill Assessment",
    to: "/skill-assessment",
    icon: <Icon><circle cx="12" cy="12" r="8.5" /><path d="m8.5 12.2 2.4 2.3 4.6-4.9" /></Icon>,
    children: [
      { label: "Skills You Know", to: "/skill-assessment" },
      { label: "DSA", to: "/skill-assessment/dsa" },
    ],
  },
  {
    label: "Mock Interview",
    to: "/interview",
    icon: (
      <Icon>
        <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="23" />
        <line x1="8" y1="23" x2="16" y2="23" />
      </Icon>
    ),
  },
  {
    label: "Resume",
    to: "/resume",
    icon: (
      <Icon>
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
        <polyline points="10 9 9 9 8 9" />
      </Icon>
    ),
    children: [
      { label: "ATS Tester", to: "/resume/ats-tester" },
      { label: "Resume Builder", to: "/resume" },
    ],
  },
  {
    label: "Roadmap",
    to: "/roadmap",
    icon: <Icon><circle cx="6" cy="18" r="2.2" /><circle cx="18" cy="6" r="2.2" /><path d="M8.2 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.8" /></Icon>,
  },
  {
    label: "Revision",
    to: "/revision",
    icon: <Icon><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5z" /><path d="M4 5.5v16" /><path d="M8 7h8M8 11h8" /></Icon>,
  },
  // Pages not built yet — shown so students know they're coming
  {
    label: "Resources",
    to: "",
    soon: true,
    icon: <Icon><path d="M4.5 5.5a2 2 0 0 1 2-2h13v14h-13a2 2 0 0 0-2 2z" /><path d="M4.5 19.5a2 2 0 0 0 2 1h13v-3" /></Icon>,
  },
  {
    label: "Opportunities",
    to: "",
    soon: true,
    icon: <Icon><rect x="3.5" y="7.5" width="17" height="12" rx="2" /><path d="M9 7.5V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v1.5" /><path d="M3.5 12.5h17" /></Icon>,
  },
];

type SidebarProps = { open: boolean; onNavigate: () => void };

const RESULTS_PATH = "/analysis/results";

/**
 * Analysis links are sections of one scrolling page: they're active when that section is on screen.
 * Every other link is active when the path and hash match.
 */
const matches = (to: string, pathname: string, hash: string, onScreen: string | null) => {
  const [path, h] = to.split("#");
  if (path === RESULTS_PATH && h && ANALYSIS_SECTION_IDS.includes(h)) return pathname === path && onScreen === h;
  // Career Track stays highlighted on its career and skill pages
  if (path === "/career-track") return pathname === path || pathname.startsWith(`${path}/`);
  if (path === "/resume" || path === "/resume/ats-tester") return pathname === path || pathname.startsWith("/resume");
  return pathname === path && (!h || hash === `#${h}`);
};

const groupHasPath = (item: NavItem, pathname: string, hash: string, onScreen: string | null) =>
  !!item.children?.some((c) => matches(c.to, pathname, hash, onScreen));

export default function Sidebar({ open, onNavigate }: SidebarProps) {
  const { pathname, hash } = useLocation();
  const navigate = useNavigate();
  const { signOut } = useAuth();
  const [loggingOut, setLoggingOut] = useState(false);
  const onScreen = useSyncExternalStore(subscribeActiveSection, getActiveSection);

  // Change your evidence or your role and the results stop describing you. The dot says so
  // from wherever you are, because the page that's now wrong is one you may not be looking at.
  const results = useSyncExternalStore(subscribePageData, resultsPageData.peek);
  const analysisState = useSyncExternalStore(subscribePageData, analysisStateData.peek);
  const evidence = useSyncExternalStore(subscribePageData, evidencePageData.peek);
  const stale = freshness({
    analysis: results?.analysis,
    targetRole: (analysisState ?? evidence?.analysisState)?.target_role,
  });
  // The group the current page belongs to: the analysis page (whichever section is showing),
  // or a group with a sub-page at this address, like Skill Assessment → DSA
  const pageGroup =
    pathname === RESULTS_PATH
      ? "Analysis"
      : items.find((i) => i.children?.some((c) => !c.to.includes("#") && c.to === pathname))?.label ?? null;
  // Start with the current page's group open, so you can see where you are
  const [expanded, setExpanded] = useState<string | null>(pageGroup);

  // Arriving on a page in a group opens that group's list
  const [lastGroup, setLastGroup] = useState(pageGroup);
  if (pageGroup !== lastGroup) {
    setLastGroup(pageGroup);
    if (pageGroup) setExpanded(pageGroup);
  }

  const toggleGroup = (label: string) => setExpanded((cur) => (cur === label ? null : label));

  const handleLogout = async () => {
    setLoggingOut(true);
    onNavigate();
    try {
      await signOut();
    } finally {
      navigate("/login", { replace: true });
    }
  };

  const isActive = (to: string) => matches(to, pathname, hash, onScreen);

  const renderLink = (item: NavItem, sub = false) =>
    item.soon ? (
      // Not a link and not focusable: there's nothing to open yet, and it says so
      <span key={item.label} className="sidebar__link sidebar__link--soon" title={`${item.label} is coming soon`}>
        {item.icon}
        <span className="sidebar__text">{item.label}</span>
        <span className="sidebar__badge">Soon</span>
      </span>

    ) : (
      <Link
        key={item.label}
        to={item.to}
        className={`sidebar__link${sub ? " sidebar__link--sub" : ""}${isActive(item.to) ? " is-active" : ""}`}
        aria-current={isActive(item.to) ? "page" : undefined}
        onClick={onNavigate}
      >
        {item.icon}
        <span className="sidebar__text">{item.label}</span>
      </Link>
    );

  return (
    <aside id="app-sidebar" className={`sidebar${open ? " is-open" : ""}`} aria-label="Main navigation" aria-hidden={!open}>
      <nav className="sidebar__nav">
        {items.map((item) =>
          item.children ? (
            <div key={item.label} className="sidebar__group">
              <button
                type="button"
                className={`sidebar__link sidebar__group-toggle${expanded === item.label ? " is-expanded" : ""}${
                  groupHasPath(item, pathname, hash, onScreen) ? " has-active" : ""
                }`}
                aria-expanded={expanded === item.label}
                onClick={() => toggleGroup(item.label)}
              >
                {item.icon}
                <span className="sidebar__text">{item.label}</span>
                {stale.stale && item.to === RESULTS_PATH && (
                  <span className="sidebar__dot" title={staleLabel(stale.reason)}>
                    <span className="sidebar__visually-hidden">{staleLabel(stale.reason)} — run the analysis again</span>
                  </span>
                )}
                <svg className="sidebar__chevron" width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                  <path d="M3.5 5.25 7 8.75l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {expanded === item.label && (
                <div className="sidebar__submenu">{item.children.map((child) => renderLink(child, true))}</div>
              )}
            </div>
          ) : (
            renderLink(item)
          )
        )}
      </nav>

      {/* Always reachable, even on a phone where the account menu is out of the way */}
      <div className="sidebar__foot">
        <button
          type="button"
          className="sidebar__link sidebar__link--logout"
          onClick={handleLogout}
          disabled={loggingOut}
        >
          <Icon><path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h7.5a2 2 0 0 0 2-2v-2.5" /><path d="M10 12h10" /><path d="m17.5 8.5 3.5 3.5-3.5 3.5" /></Icon>
          <span className="sidebar__text">{loggingOut ? "Logging out…" : "Log out"}</span>
        </button>
      </div>
    </aside>
  );
}
