import { apiFetch } from "./api";

export interface NotionEvidenceItem {
  skill: string;
  canonical_name?: string;
  evidenceType: "demonstrated" | "implemented" | "practiced" | "studied" | "mentioned";
  confidence: number;
  signal_strength: number;
  depth: number;
  topics: string[];
  excerpt?: string;
  sourcePageId?: string;
  sourcePageTitle?: string;
  sourceUrl?: string;
  timestamp?: string;
}

export interface NotionSyncedPage {
  page_id: string;
  page_title: string;
  page_url: string;
  last_edited_time?: string | null;
  content_summary?: string | null;
  skills: string[];
  headings: string[];
  code_languages: string[];
  word_count: number;
  extracted_evidence: NotionEvidenceItem[];
}

export interface NotionStatus {
  connected: boolean;
  status: "connected" | "disconnected" | "revoked" | "reconnect_required";
  workspace_name?: string | null;
  workspace_icon?: string | null;
  workspace_id?: string | null;
  bot_id?: string | null;
  last_synced_at?: string | null;
  synced_pages_count: number;
  evidence_count: number;
  synced_pages?: NotionSyncedPage[];
}

export interface NotionConnectResponse {
  authorization_url: string;
}

export interface NotionSyncResult {
  status: string;
  pages_scanned: number;
  pages_with_evidence: number;
  evidence_count: number;
  skills_detected: string[];
  last_synced_at: string;
  details: Array<{
    page_id: string;
    page_title: string;
    page_url?: string;
    last_edited_time?: string;
    content_summary?: string;
    skills: string[];
    headings?: string[];
    code_languages?: string[];
    word_count?: number;
    evidence_count: number;
    extracted_evidence?: NotionEvidenceItem[];
  }>;
  synced_pages?: NotionSyncedPage[];
}

export interface NotionDisconnectResponse {
  status: string;
  message: string;
}

export async function getNotionStatus(): Promise<NotionStatus> {
  return apiFetch<NotionStatus>("/integrations/notion/status");
}

export async function getNotionPages(): Promise<NotionSyncedPage[]> {
  return apiFetch<NotionSyncedPage[]>("/integrations/notion/pages");
}

export async function getNotionConnectUrl(): Promise<string> {
  const resp = await apiFetch<NotionConnectResponse>("/integrations/notion/connect");
  return resp.authorization_url;
}

export async function syncNotion(): Promise<NotionSyncResult> {
  return apiFetch<NotionSyncResult>("/integrations/notion/sync", {
    method: "POST",
  });
}

export async function disconnectNotion(): Promise<NotionDisconnectResponse> {
  return apiFetch<NotionDisconnectResponse>("/integrations/notion/disconnect", {
    method: "DELETE",
  });
}
