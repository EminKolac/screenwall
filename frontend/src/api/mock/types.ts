import type { DocStatus, FileKind, ItemKind, Lang, Mode, ReviewReason, SpanState, UnitKind } from "../contract";

export interface MockUnit {
  id: string;
  block_id: string;
  kind: UnitKind;
  page: number | null;
  location: string;
  table: { id: string; row: number; col: number } | null;
  original: string;
}

export interface MockSpan {
  id: string;
  unit_id: string;
  start: number;
  end: number;
  family: string;
  placeholder: string;
  evidence: string[];
  reason: string;
  state: SpanState;
}

export interface MockItem {
  id: string;
  kind: ItemKind;
  unit_id: string;
  start: number;
  end: number;
  family: string | null;
  reason: string;
  status: "open" | "masked" | "kept";
}

export type PageStyle = "slide" | "a4";

export interface MockPage {
  index: number;
  width: number;
  height: number;
  style: PageStyle;
  unreadable: boolean;
}

export interface Processing {
  start: number;
  duration: number;
  outcome: "needs_review" | "approved" | "failed";
}

export interface MockDoc {
  id: string;
  filename: string;
  kind: FileKind;
  mode: Mode;
  language: Lang;
  createdAt: number;
  updatedAt: number;
  /** Final status once processing is over (needs_review, approved, rejected, failed). */
  status: DocStatus;
  /** Like the backend: 0 until anonymized, then +1 per (re-)anonymization, i.e. per decision. */
  revision: number;
  processing: Processing | null;
  units: MockUnit[];
  spans: MockSpan[];
  items: MockItem[];
  pages: MockPage[];
  reasons: ReviewReason[];
  /** entity key → placeholder, so repeated values share a placeholder. */
  placeholders: Record<string, string>;
  seq: number;
}

export interface MockLists {
  always_mask: string[];
  never_mask: string[];
}
