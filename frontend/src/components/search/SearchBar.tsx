import { useCallback, useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { renderText } from "./typewriter";
import { useTypewriter } from "./useTypewriter";
import "./SearchBar.css";

const DEFAULT_WORDS = ["skills", "roles", "resources"] as const;

type SearchBarProps = {
  /** Called on Enter with the trimmed query. Search isn't built yet, so this is optional. */
  onSubmit?: (query: string) => void;
  /** Called on every keystroke, for live results later */
  onQueryChange?: (query: string) => void;
  words?: readonly string[];
  prefix?: string;
  /** Listen for Ctrl/⌘ + K anywhere on the page */
  enableShortcut?: boolean;
  className?: string;
};

const isApple = () => {
  if (typeof navigator === "undefined") return false;
  const platform =
    (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform || navigator.platform || navigator.userAgent;
  return /mac|iphone|ipad|ipod/i.test(platform);
};

export default function SearchBar({
  onSubmit,
  onQueryChange,
  words = DEFAULT_WORDS,
  prefix = "Search for",
  enableShortcut = true,
  className = "",
}: SearchBarProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  // On phones the bar starts as an icon and expands over the top bar
  const [expanded, setExpanded] = useState(false);
  const [apple] = useState(isApple);
  const hintId = useId();

  // The animation only runs while nobody is using the field
  const idle = !focused && query === "";
  const { state, animating } = useTypewriter(words, idle);
  // Once focused, finish the current word rather than freezing halfway through it
  const placeholder = focused
    ? renderText(prefix, "...", { ...state, chars: words[state.wordIndex]?.length ?? 0 }, words)
    : renderText(prefix, "...", state, words);

  const open = useCallback(() => {
    setExpanded(true);
    // Wait a frame so the expanded input is visible before focusing it
    requestAnimationFrame(() => inputRef.current?.focus({ preventScroll: true }));
  }, []);

  useEffect(() => {
    if (!enableShortcut) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        open();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enableShortcut, open]);

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      inputRef.current?.blur();
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (q) onSubmit?.(q);
  };

  return (
    <form
      role="search"
      className={`search${focused ? " is-focused" : ""}${expanded ? " is-expanded" : ""} ${className}`.trim()}
      onSubmit={handleSubmit}
    >
      {/* Phones: compact icon that opens the full field */}
      <button type="button" className="search__trigger" aria-label="Search" onClick={open}>
        <SearchIcon />
      </button>

      <div className="search__field" onMouseDown={(e) => {
        // Clicking anywhere on the pill (icon, padding) focuses the input
        if (e.target !== inputRef.current) {
          e.preventDefault();
          inputRef.current?.focus({ preventScroll: true });
        }
      }}>
        <span className="search__icon" aria-hidden="true">
          <SearchIcon />
        </span>

        <div className="search__control">
          <input
            ref={inputRef}
            type="search"
            className="search__input"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              onQueryChange?.(e.target.value);
            }}
            onFocus={() => setFocused(true)}
            onBlur={() => {
              setFocused(false);
              if (!inputRef.current?.value) setExpanded(false);
            }}
            onKeyDown={handleKeyDown}
            aria-label={`${prefix} ${words.join(", ")}`}
            aria-describedby={hintId}
            autoComplete="off"
            spellCheck={false}
            enterKeyHint="search"
          />
          {query === "" && (
            <span className={`search__placeholder${animating ? " is-typing" : ""}`} aria-hidden="true">
              {placeholder}
              <span className="search__cursor" />
            </span>
          )}
        </div>

        <kbd className="search__kbd" id={hintId} aria-label={focused ? "Press Escape to close" : `Press ${apple ? "Command" : "Control"} K to search`}>
          {focused ? (
            <span>Esc</span>
          ) : (
            <>
              <span className={apple ? "search__kbd-cmd" : ""}>{apple ? "⌘" : "Ctrl"}</span>
              <span>K</span>
            </>
          )}
        </kbd>
      </div>
    </form>
  );
}

function SearchIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="7.1" cy="7.1" r="4.6" stroke="currentColor" strokeWidth="1.5" />
      <path d="m10.6 10.6 3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
