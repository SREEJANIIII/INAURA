import type { ResumeContent } from "../../../services/resumeBuilder";

/**
 * Shared presentational helpers for resume templates.
 *
 * These build display fragments (contact rows, link labels) from the
 * canonical ResumeData. They never generate, filter, or mutate content —
 * every template renders the same data through them.
 */

export type ContactPart = { label: string; url?: string };

export function hostLabel(url: string, fallback: string): string {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    if (host.includes("github")) return fallback && fallback !== "Link" ? fallback : "GitHub";
    if (host.includes("linkedin")) return "LinkedIn";
    return fallback && fallback !== "Link" ? fallback : host;
  } catch {
    return fallback || url;
  }
}

export function getContactParts(header: NonNullable<ResumeContent["header"]>): ContactPart[] {
  const parts: ContactPart[] = [];
  if (header.email) parts.push({ label: header.email, url: `mailto:${header.email}` });
  if (header.phone) parts.push({ label: header.phone });
  for (const link of header.links ?? []) {
    if (link?.url) parts.push({ label: link.label || hostLabel(link.url, "Link"), url: link.url });
  }
  return parts;
}

export function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}
