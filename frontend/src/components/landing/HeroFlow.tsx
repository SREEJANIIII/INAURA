import type { LucideIcon } from "lucide-react";
import { Award, BookOpen, Briefcase, Code2, FileText, FolderGit2, Milestone, Route, Target } from "lucide-react";
import { motion } from "framer-motion";
import { EASE } from "./scroll";
import "./shared.css";
import "./HeroFlow.css";

type Item = { label: string; icon: LucideIcon };

const INPUTS: Item[] = [
  { label: "GitHub", icon: Code2 },
  { label: "Projects", icon: FolderGit2 },
  { label: "Certifications", icon: Award },
  { label: "Resume", icon: FileText },
  { label: "Learning", icon: BookOpen },
];

const OUTPUTS: Item[] = [
  { label: "Skill gaps", icon: Target },
  { label: "Career Track", icon: Route },
  { label: "Roadmap", icon: Milestone },
  { label: "Opportunities", icon: Briefcase },
];

function Group({ label, items, from }: { label: string; items: Item[]; from: number }) {
  return (
    <div className="hflow__group">
      <span className="lp-kicker">{label}</span>
      <ul className="lp-chips hflow__chips">
        {items.map((item, i) => (
          <motion.li
            key={item.label}
            className="lp-chip hflow__chip"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: EASE, delay: from + i * 0.06 }}
          >
            <item.icon aria-hidden="true" />
            {item.label}
          </motion.li>
        ))}
      </ul>
    </div>
  );
}

/** The hero's small product preview: what goes in, what INAURA does with it, what comes out */
export default function HeroFlow() {
  return (
    <figure className="hflow">
      <figcaption className="lp-sr">
        INAURA reads your GitHub, projects, certifications, resume and learning, analyzes them against
        your target role, and gives you skill gaps, a Career Track, a roadmap and opportunities.
      </figcaption>
      <div className="hflow__inner" aria-hidden="true">
        <Group label="Your evidence" items={INPUTS} from={0.9} />

        <span className="hflow__link">
          <span className="hflow__pulse" />
        </span>

        <motion.div
          className="hflow__core"
          initial={{ opacity: 0, scale: 0.94 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.7, ease: EASE, delay: 1.2 }}
        >
          <span className="hflow__core-name">INAURA</span>
          <span className="hflow__core-sub">Analysis</span>
          <span className="hflow__core-note">Evidence vs. role requirements</span>
        </motion.div>

        <span className="hflow__link">
          <span className="hflow__pulse" />
        </span>

        <Group label="Your path" items={OUTPUTS} from={1.35} />
      </div>
    </figure>
  );
}
