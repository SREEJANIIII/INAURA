import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { phrasesFor, renderText } from "./typewriter";
import { useTypewriter } from "./useTypewriter";
import { SEARCH_SUGGESTIONS, shuffled } from "./suggestions";
import type { SearchResult } from "./searchIndex";
import "./SearchBar.css";

type SearchBarProps = {
  /** Called on Enter when nothing in the list is picked */
  onSubmit?: (query: string) => void;
  /** Called on every keystroke, so the parent can work out the results */
  onQueryChange?: (query: string) => void;
  /** Matches for what's been typed, best first */
  results?: SearchResult[];
  /** Called when a result is clicked or chosen with the keyboard */
  onSelect?: (result: SearchResult) => void;
  words?: readonly string[];
  prefix?: string;
  /** Listen for Ctrl/⌘ + K anywhere on the page */
  enableShortcut?: boolean;
  /** Some of what can be searched hasn't loaded yet, so "no matches" may not be the last word */
  pending?: boolean;
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
  results = [],
  onSelect,
  words,
  prefix = "Search for",
  enableShortcut = true,
  pending = false,
  className = "",
}: SearchBarProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [focused, setFocused] = useState(false);
  // On phones the bar starts as an icon and expands over the top bar
  const [expanded, setExpanded] = useState(false);
  const [apple] = useState(isApple);
  const [active, setActive] = useState(0);
  const hintId = useId();
  const listId = useId();

  // A different order each time the bar loads, so it isn't always the same few words
  const suggestions = useMemo(() => words ?? shuffled(SEARCH_SUGGESTIONS), [words]);
  // The dots belong to the word, so they're erased and written along with it
  const phrases = useMemo(() => phrasesFor(suggestions), [suggestions]);

  // The animation only runs while nobody is using the field
  const idle = !focused && query === "";
  const { state, animating } = useTypewriter(phrases, idle);
  // Once focused, finish the current word rather than freezing halfway through it
  const placeholder = focused
    ? renderText(prefix, { ...state, chars: phrases[state.wordIndex]?.length ?? 0 }, phrases)
    : renderText(prefix, state, phrases);

  const typed = query.trim();
  const showResults = focused && typed !== "";
  const chosen = results[active] ?? results[0];

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

  const close = () => {
    setQuery("");
    onQueryChange?.("");
    setActive(0);
    inputRef.current?.blur();
  };

  const pick = (result: SearchResult) => {
    onSelect?.(result);
    close();
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }
    if (!showResults || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (i + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (i - 1 + results.length) % results.length);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!typed) return;
    // Enter opens whatever is highlighted; only with nothing to open does it fall back
    if (chosen) pick(chosen);
    else onSubmit?.(typed);
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
            role="combobox"
            aria-expanded={showResults}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={showResults && chosen ? `${listId}-${results.indexOf(chosen)}` : undefined}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
              onQueryChange?.(e.target.value);
            }}
            onFocus={() => setFocused(true)}
            onBlur={() => {
              setFocused(false);
              if (!inputRef.current?.value) setExpanded(false);
            }}
            onKeyDown={handleKeyDown}
            aria-label="Search INAURA"
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

      {showResults && (
        <div className="search__panel">
          {results.length === 0 ? (
            <p className="search__empty" role="status">
              {pending ? `Still loading your data — nothing for “${typed}” yet` : `No matches for “${typed}”`}
            </p>
          ) : (
            <ul className="search__list" id={listId} role="listbox" aria-label="Search results">
              {results.map((result, i) => (
                <li key={result.id} role="presentation">
                  <button
                    type="button"
                    id={`${listId}-${i}`}
                    role="option"
                    aria-selected={result === chosen}
                    className={`search__result${result === chosen ? " is-active" : ""}`}
                    // Keeps focus on the input, so the panel doesn't close before the click lands
                    onMouseDown={(e) => e.preventDefault()}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => pick(result)}
                  >
                    <span className="search__result-text">
                      <span className="search__result-label">{result.label}</span>
                      {result.detail && <span className="search__result-detail">{result.detail}</span>}
                    </span>
                    <span className="search__result-kind">{result.kind}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
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
