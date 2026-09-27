import type { SkillState } from "./journeyModel";

/**
 * Each skill state has its own shape as well as its own colour, so the map still reads in
 * greyscale or to someone who can't tell the colours apart: a solid dot for proven, a ringed
 * dot for building, a half-filled dot for needs proof, a triangle for a priority gap, a lock,
 * and an empty ring for upcoming.
 */
export function GlyphShape({ state }: { state: SkillState }) {
  switch (state) {
    case "proven":
      return (
        <>
          <circle r="5.4" className="jr-g jr-g--proven" />
          <path d="M-2.6 0.1 -0.8 1.9 2.7 -1.8" className="jr-g-tick" />
        </>
      );
    case "building":
      return (
        <>
          <circle r="5" className="jr-g-ring jr-g-ring--building" />
          <circle r="2.1" className="jr-g jr-g--building" />
        </>
      );
    case "needs-proof":
      return (
        <>
          <circle r="5" className="jr-g-ring jr-g-ring--needs-proof" />
          <path d="M0 -5 A5 5 0 0 0 0 5 Z" className="jr-g jr-g--needs-proof" />
        </>
      );
    case "priority-gap":
      return <path d="M0 -6 5.6 4.2 -5.6 4.2 Z" className="jr-g jr-g--priority-gap" />;
    case "locked":
      return (
        <>
          <path d="M-2.4 -1.2 V-2.9 A2.4 2.4 0 0 1 2.4 -2.9 V-1.2" className="jr-g-shackle" />
          <rect x="-4.3" y="-1.4" width="8.6" height="6.6" rx="1.4" className="jr-g jr-g--locked" />
        </>
      );
    default:
      return <circle r="4.6" className="jr-g-ring jr-g-ring--upcoming" />;
  }
}

/** The state's shape as a small standalone icon, for legends and lists */
export default function StateGlyph({ state, size = 14 }: { state: SkillState; size?: number }) {
  return (
    <svg className="jr-glyph" width={size} height={size} viewBox="-7 -7 14 14" aria-hidden="true" focusable="false">
      <GlyphShape state={state} />
    </svg>
  );
}
