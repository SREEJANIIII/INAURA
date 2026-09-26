import { useEffect, useRef, useState } from "react";

type Shared = {
  value: string;
  onCommit: (value: string) => void;
  ariaLabel: string;
};

/**
 * Click-to-edit text that looks like document content until focused.
 * Draft lives locally; the parent state handler fires once on commit
 * (blur or Enter). Escape cancels. Plain text only — no rich editing.
 */
function useDraft(value: string) {
  const [draft, setDraft] = useState(value);
  const [editing, setEditing] = useState(false);
  const start = () => {
    setDraft(value);
    setEditing(true);
  };
  return { draft, setDraft, editing, setEditing, start };
}

export function EditableBullet({ value, onCommit, ariaLabel }: Shared) {
  const { draft, setDraft, editing, setEditing, start } = useDraft(value);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing ]);

  if (!editing) {
    return (
      <span
        className="rdoc-editable"
        role="button"
        tabIndex={0}
        aria-label={ariaLabel}
        title="Click to edit"
        onClick={start}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            start();
          }
        }}
      >
        {value}
      </span>
    );
  }
  return (
    <input
      ref={inputRef}
      className="rdoc-input rdoc-bullet-input"
      aria-label={ariaLabel}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        setEditing(false);
        if (draft !== value) onCommit(draft);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        if (e.key === "Escape") setEditing(false);
      }}
    />
  );
}

export function EditableSummary({ value, onCommit, ariaLabel }: Shared) {
  const { draft, setDraft, editing, setEditing, start } = useDraft(value);
  const areaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editing) {
      areaRef.current?.focus();
      areaRef.current?.setSelectionRange(areaRef.current.value.length, areaRef.current.value.length);
    }
  }, [editing]);

  if (!editing) {
    return (
      <span
        className="rdoc-editable rdoc-editable-block"
        role="button"
        tabIndex={0}
        aria-label={ariaLabel}
        title="Click to edit"
        onClick={start}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            start();
          }
        }}
      >
        {value}
      </span>
    );
  }
  return (
    <textarea
      ref={areaRef}
      className="rdoc-input rdoc-summary-input"
      aria-label={ariaLabel}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        setEditing(false);
        if (draft !== value) onCommit(draft);
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") setEditing(false);
      }}
    />
  );
}
