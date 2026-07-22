export interface DocSummary {
  id: string;
  filename: string;
  kind: string;
  language: string;
  status: string;
  status_label: string;
  iterations: number;
  approved: boolean;
  chat_enabled: boolean;
  risk_level: string | null;
  has_anonymized: boolean;
}

export interface SensitiveItem {
  type: string;
  snippet: string;
  location: string;
  note: string;
}

export interface AuditResult {
  approved: boolean;
  risk_level: string;
  remaining_sensitive_items: SensitiveItem[];
  summary: string;
  recommended_next_action: string;
}

export interface IterationRecord {
  iteration: number;
  presidio_entities: number;
  placeholders_used: Record<string, number>;
  by_source?: Record<string, number>; // masked spans per detection stage (presidio / privacy_filter / deny)
  audit: AuditResult | null;
  created_at: string;
}

export interface DocDetail {
  id: string;
  filename: string;
  kind: string;
  language: string;
  status: string;
  current_iteration: number;
  iterations: IterationRecord[];
  created_at: string;
  updated_at: string;
  chat_ready?: boolean;
}

export interface StatusInfo {
  value: string;
  label: string;
}

export type ChatMessage = { role: "user" | "assistant"; content: string };
