import { useEffect, useState } from "react";
import "./Person2.css";
import {
  createEmployer,
  createRequirement,
  listEmployers,
  listRequirements,
  type Employer,
  type Requirement,
} from "../services/employers";

const messageOf = (e: unknown) => (e instanceof Error ? e.message : String(e));

export default function Employers() {
  const [employers, setEmployers] = useState<Employer[]>([]);
  const [selected, setSelected] = useState<Employer | null>(null);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("");
  const [title, setTitle] = useState("");
  const [roleKey, setRoleKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const refresh = () =>
    listEmployers()
      .then((rows) => {
        setEmployers(rows);
        if (selected) {
          const still = rows.find((r) => r.id === selected.id) ?? null;
          setSelected(still);
        }
      })
      .catch((e) => setError(messageOf(e)));

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) {
      setRequirements([]);
      return;
    }
    listRequirements(selected.id)
      .then(setRequirements)
      .catch((e) => setError(messageOf(e)));
  }, [selected]);

  const addEmployer = async () => {
    if (!name.trim()) {
      setError("Company name is required");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const row = await createEmployer({ name: name.trim(), industry: industry.trim() || null });
      setName("");
      setIndustry("");
      const rows = await listEmployers();
      setEmployers(rows);
      setSelected(rows.find((r) => r.id === row.id) ?? row);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  const addRequirement = async () => {
    if (!selected || !title.trim()) {
      setError("Pick an employer and enter a role title");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createRequirement(selected.id, {
        title: title.trim(),
        role_key: roleKey.trim() || null,
      });
      setTitle("");
      setRoleKey("");
      setRequirements(await listRequirements(selected.id));
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <main className="p2">
      <header className="p2__head">
        <h1>Employers</h1>
        <p>Companies you interact with, and the roles they are hiring for.</p>
      </header>
      {error && <p className="p2__error">{error}</p>}
      <div className="p2__cols">
        <section>
          <h2>Your employers</h2>
          <ul className="p2__list">
            {employers.map((e) => (
              <li key={e.id}>
                <button
                  type="button"
                  className={`p2__pick${selected?.id === e.id ? " is-active" : ""}`}
                  onClick={() => setSelected(e)}
                >
                  <strong>{e.name}</strong>
                  {e.industry && <span> · {e.industry}</span>}
                  {e.location && <span> · {e.location}</span>}
                </button>
              </li>
            ))}
            {employers.length === 0 && <li>No employers yet — add your first below.</li>}
          </ul>
          <div className="p2__form">
            <input
              aria-label="Company name"
              placeholder="Company name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <input
              aria-label="Industry"
              placeholder="Industry (optional)"
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
            />
            <button type="button" onClick={addEmployer} disabled={saving}>
              {saving ? "Saving…" : "Add employer"}
            </button>
          </div>
        </section>
        <section>
          <h2>Hiring requirements</h2>
          {!selected ? (
            <p>Select an employer to see its roles.</p>
          ) : (
            <>
              <ul className="p2__list">
                {requirements.map((r) => (
                  <li key={r.id} className="p2__card">
                    <strong>{r.title}</strong>
                    {r.role_key && <span> · {r.role_key}</span>}
                    {r.location && <span> · {r.location}</span>}
                    <em> · {r.status}</em>
                  </li>
                ))}
                {requirements.length === 0 && <li>No open roles yet for {selected.name}.</li>}
              </ul>
              <div className="p2__form">
                <input
                  aria-label="Role title"
                  placeholder="Role title (e.g. Backend Intern)"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                />
                <input
                  aria-label="Industry role key"
                  placeholder="Industry role key (optional)"
                  value={roleKey}
                  onChange={(e) => setRoleKey(e.target.value)}
                />
                <button type="button" onClick={addRequirement} disabled={saving}>
                  {saving ? "Saving…" : "Add requirement"}
                </button>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
