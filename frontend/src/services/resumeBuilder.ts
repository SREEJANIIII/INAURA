import { apiFetch, apiFetchBlob } from "./api";

export type ResumeProject = { name: string; technologies: string[]; description: string; bullets: string[]; links: string[] };
export type ResumeContent = { header?: { name?: string; email?: string; phone?: string; links?: { label?: string; url?: string }[] }; summary?: string; education?: any[]; skills?: string[]; skill_groups?: Record<string, string[]>; projects?: ResumeProject[]; certifications?: any[]; experience?: any[]; achievements?: any[] };
export type Resume = { id: string; title: string; target_role: string; template: string; content: ResumeContent; claims: any[]; created_at?: string; updated_at?: string };
export type ResumeFinding = { status: string; reason: string; section?: string; claim_id?: string; matches?: string[] };

export const listResumes = () => apiFetch<Resume[]>("/resumes");
export const createResume = (payload: { target_role: string; title?: string; template?: string }) => apiFetch<Resume>("/resumes", { method: "POST", body: JSON.stringify(payload) });
export const updateResume = (id: string, payload: Partial<Pick<Resume, "title" | "target_role" | "template" | "content">>) => apiFetch<Resume>(`/resumes/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
export const verifyResume = (id: string) => apiFetch<{ status: string; findings: ResumeFinding[] }>(`/resumes/${id}/verify`, { method: "POST" });
export const exportLatex = async (id: string) => (await apiFetchBlob(`/resumes/${id}/latex`)).text();

export function submitToOverleaf(latex: string): void {
  if (!/^\\documentclass(?:\[[^\]]*\])?\{[^}]+\}/m.test(latex) || !/\\begin\{document\}/.test(latex) || !/\\end\{document\}/.test(latex)) {
    throw new Error("This resume does not contain a complete LaTeX document.");
  }
  const form = document.createElement("form");
  form.action = "https://www.overleaf.com/docs";
  form.method = "post";
  form.target = "_blank";
  const fields: Record<string, string> = { encoded_snip: encodeURIComponent(latex), engine: "pdflatex", main_document: "main.tex" };
  Object.entries(fields).forEach(([name, value]) => { const input = document.createElement("input"); input.type = "hidden"; input.name = name; input.value = value; form.appendChild(input); });
  document.body.appendChild(form); form.submit(); form.remove();
}
