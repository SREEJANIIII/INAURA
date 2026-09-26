import { EditableBullet } from "../EditableText";

type BulletsProps = {
  bullets: string[];
  projectName: string;
  editing?: { onBulletChange: (bulletIndex: number, value: string) => void };
};

/** Bullet list renderer shared by templates (same data, same edit wiring). */
export function TemplateBullets({ bullets, projectName, editing }: BulletsProps) {
  return (
    <ul className="rdoc-list">
      {bullets.map((bullet, bi) => (
        <li key={bi}>
          {editing ? (
            <EditableBullet
              value={bullet}
              ariaLabel={`Bullet ${bi + 1} for ${projectName}. Activate to edit.`}
              onCommit={(value) => editing.onBulletChange(bi, value)}
            />
          ) : (
            bullet
          )}
        </li>
      ))}
    </ul>
  );
}
