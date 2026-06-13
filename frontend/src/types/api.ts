export type User = {
  id: string;
  email: string;
  name: string;
};

export type Workspace = {
  id: string;
  name: string;
  owner_id: string;
  voice_style_preference?: "auto" | "english" | "hinglish" | "tanglish" | "regional_mix";
};

export type DocumentRecord = {
  id: string;
  workspace_id: string;
  uploaded_by?: string;
  filename: string;
  file_type: string;
  storage_path?: string;
  status: string;
  checksum?: string;
  error_message?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type WikiPage = {
  id: string;
  workspace_id?: string;
  title: string;
  path: string;
  summary: string;
  content: string;
  created_from_document_ids?: string[];
  created_at?: string;
  updated_at?: string;
};

export type WikiAbsorbLog = {
  id: string;
  workspace_id: string;
  document_id: string;
  storage_path: string;
  decisions: Record<string, unknown>[];
  action_counts: Record<string, number>;
  created_at: string;
};

export type WikiRevision = {
  id: string;
  workspace_id: string;
  page_id: string;
  title: string;
  content: string;
  summary: string;
  edited_by: string;
  edit_actor: string;
  edit_note?: string | null;
  created_at: string;
};

export type WikiMaintenanceLog = {
  id: string;
  workspace_id: string;
  status: string;
  action: string;
  details: Record<string, unknown>;
  created_at: string;
};

export type Citation = {
  document_id: string | null;
  filename: string | null;
  page_number: number | null;
  chunk_id: string | null;
  quote: string | null;
};

export type AskResponse = {
  answer: string;
  conversation_id: string;
  message_id?: string;
  citations: Citation[];
  retrieved_context?: SearchResult[];
  latency?: Record<string, number>;
  context_stats?: Record<string, unknown>;
};

export type SearchResult = {
  chunk_id: string;
  score: number;
  source_type: string;
  content: string;
  payload: Record<string, unknown>;
};

export type ExtractedPage = {
  page_number: number;
  text: string;
  headings: string[];
  tables: Record<string, unknown>[];
};

export type ExtractedDocument = {
  document_id?: string;
  filename?: string;
  file_type?: string;
  pages?: ExtractedPage[];
};

export type SourceResponse = {
  document: DocumentRecord;
  extracted: ExtractedDocument;
  wiki_pages: WikiPage[];
};

export type ConversationSummary = {
  id: string;
  workspace_id: string;
  user_id: string;
  mode: string;
  title?: string;
  message_count?: number;
  created_at: string;
  updated_at: string;
};

export type ConversationMessage = {
  id: string;
  role: "user" | "assistant" | string;
  content: string;
  created_at: string;
};

export type ConversationDetail = Omit<ConversationSummary, "created_at" | "updated_at"> & {
  created_at?: string;
  updated_at?: string;
  messages: ConversationMessage[];
};

export type VoiceSession = {
  session_id: string;
  conversation_id: string;
  room_name: string;
  livekit_url: string;
  livekit_token?: string;
  status: string;
};

export type VoiceAskResponse = AskResponse & {
  transcript: string;
  audio_bytes: number;
  audio_base64?: string;
  audio_mime?: string;
  voice_latency?: Record<string, unknown>;
};

export type VoiceStreamEvent =
  | { type: "transcript"; transcript: string; voice_latency?: Record<string, unknown> }
  | {
      type: "answer";
      transcript: string;
      answer: string;
      conversation_id: string;
      message_id?: string;
      latency?: Record<string, number>;
      context_stats?: Record<string, unknown>;
    }
  | { type: "audio_start"; audio_mime: string }
  | { type: "audio_delta"; audio_base64: string; audio_bytes: number }
  | (VoiceAskResponse & { type: "final" })
  | { type: "error"; message: string };

export type HealthCheck = {
  ok: boolean;
  error?: string;
};

export type HealthDetails = {
  status: string;
  service: string;
  checks: Record<string, HealthCheck>;
};

export type MetricTiming = {
  count: number;
  total_seconds: number;
  avg_seconds: number;
  max_seconds: number;
};

export type MetricsSnapshot = {
  counters: Record<string, number>;
  timings: Record<string, MetricTiming>;
};
