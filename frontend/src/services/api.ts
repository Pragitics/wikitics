import type {
  AskResponse,
  ConversationDetail,
  ConversationSummary,
  DocumentRecord,
  HealthDetails,
  MetricsSnapshot,
  SourceResponse,
  User,
  VoiceAskResponse,
  VoiceStreamEvent,
  VoiceSession,
  WikiAbsorbLog,
  WikiMaintenanceLog,
  WikiPage,
  WikiRevision,
  Workspace
} from "../types/api";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const VOICE_UNAVAILABLE_MESSAGE = "Voice service is currently unavailable. Please try again.";

type RequestOptions = RequestInit & { token?: string | null };

async function fetchWithRetry(input: string, init: RequestInit, retries = 1): Promise<Response> {
  let attempt = 0;
  while (true) {
    try {
      return await fetch(input, init);
    } catch (error) {
      if (attempt >= retries) {
        const message =
          error instanceof Error && error.message === "Failed to fetch"
            ? "Connection interrupted. Refresh and try again."
            : error instanceof Error
              ? error.message
              : "Network request failed";
        throw new Error(message);
      }
      attempt += 1;
      await new Promise((resolve) => window.setTimeout(resolve, 300));
    }
  }
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetchWithRetry(`${API_BASE_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.error?.message || (typeof error.detail === "string" ? error.detail : "Request failed"));
  }
  return response.json() as Promise<T>;
}

export const api = {
  register: (email: string, password: string, name: string) =>
    request<{ access_token: string; user: User }>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, name })
    }),
  login: (email: string, password: string) =>
    request<{ access_token: string; user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password })
    }),
  me: (token: string) => request<User>("/api/auth/me", { token }),
  workspaces: (token: string) => request<Workspace[]>("/api/workspaces", { token }),
  createWorkspace: (token: string, name: string) =>
    request<Workspace>("/api/workspaces", { token, method: "POST", body: JSON.stringify({ name }) }),
  updateWorkspace: (
    token: string,
    workspaceId: string,
    payload: { name?: string; voice_style_preference?: Workspace["voice_style_preference"] }
  ) =>
    request<Workspace>(`/api/workspaces/${workspaceId}`, {
      token,
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  deleteWorkspace: (token: string, workspaceId: string) =>
    request<{ deleted: boolean; workspace_id: string }>(`/api/workspaces/${workspaceId}`, { token, method: "DELETE" }),
  documents: (token: string, workspaceId: string) =>
    request<DocumentRecord[]>(`/api/workspaces/${workspaceId}/documents`, { token }),
  uploadDocument: (token: string, workspaceId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentRecord>(`/api/workspaces/${workspaceId}/documents`, { token, method: "POST", body: form });
  },
  processDocument: (token: string, documentId: string) =>
    request<{ document: DocumentRecord; wiki_file_count: number }>(`/api/documents/${documentId}/process`, {
      token,
      method: "POST"
    }),
  documentSource: (token: string, documentId: string) =>
    request<SourceResponse>(`/api/documents/${documentId}/source`, { token }),
  wikiPages: (token: string, workspaceId: string) =>
    request<WikiPage[]>(`/api/workspaces/${workspaceId}/wiki`, { token }),
  wikiAbsorbLogs: (token: string, workspaceId: string) =>
    request<WikiAbsorbLog[]>(`/api/workspaces/${workspaceId}/wiki/absorb-logs`, { token }),
  maintainWiki: (token: string, workspaceId: string) =>
    request<{ workspace_id: string; status: string; issues: Record<string, unknown>[]; changed_page_ids: string[] }>(
      `/api/workspaces/${workspaceId}/wiki/maintain`,
      { token, method: "POST" }
    ),
  wikiMaintenanceLogs: (token: string, workspaceId: string) =>
    request<WikiMaintenanceLog[]>(`/api/workspaces/${workspaceId}/wiki/maintenance-logs`, { token }),
  updateWikiPage: (
    token: string,
    workspaceId: string,
    pageId: string,
    payload: { title?: string; content?: string; summary?: string; edit_note?: string; edit_actor?: string }
  ) =>
    request<WikiPage>(`/api/workspaces/${workspaceId}/wiki/pages/${pageId}`, {
      token,
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  wikiPageRevisions: (token: string, workspaceId: string, pageId: string) =>
    request<WikiRevision[]>(`/api/workspaces/${workspaceId}/wiki/pages/${pageId}/revisions`, { token }),
  revertWikiPage: (token: string, workspaceId: string, pageId: string, revisionId: string, editNote?: string) =>
    request<WikiPage>(`/api/workspaces/${workspaceId}/wiki/pages/${pageId}/revert`, {
      token,
      method: "POST",
      body: JSON.stringify({ revision_id: revisionId, edit_note: editNote })
    }),
  ask: (token: string, workspaceId: string, question: string, conversationId?: string | null) =>
    request<AskResponse>(`/api/workspaces/${workspaceId}/ask`, {
      token,
      method: "POST",
      body: JSON.stringify({ question, conversation_id: conversationId })
    }),
  conversations: (token: string, workspaceId: string) =>
    request<ConversationSummary[]>(`/api/workspaces/${workspaceId}/conversations`, { token }),
  conversation: (token: string, conversationId: string) =>
    request<ConversationDetail>(`/api/conversations/${conversationId}`, { token }),
  deleteConversation: (token: string, conversationId: string) =>
    request<{ deleted: boolean; conversation_id: string }>(`/api/conversations/${conversationId}`, {
      token,
      method: "DELETE"
    }),
  createVoiceSession: (token: string, workspaceId: string, conversationId?: string | null) =>
    request<VoiceSession>(`/api/workspaces/${workspaceId}/voice/session`, {
      token,
      method: "POST",
      body: JSON.stringify({ conversation_id: conversationId })
    }),
  askVoice: (token: string, sessionId: string, transcript: string) =>
    request<VoiceAskResponse>(`/api/voice/session/${sessionId}/ask`, {
      token,
      method: "POST",
      body: JSON.stringify({ transcript })
    }),
  askVoiceTranscriptStream: async (
    token: string,
    sessionId: string,
    transcript: string,
    onEvent: (event: VoiceStreamEvent) => void,
    signal?: AbortSignal
  ): Promise<VoiceAskResponse> => {
    const response = await fetchWithRetry(`${API_BASE_URL}/api/voice/session/${sessionId}/ask/stream`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ transcript }),
      signal
    });
    return readVoiceStreamResponse(response, onEvent);
  },
  askVoiceAudio: (token: string, sessionId: string, audio: Blob) => {
    const form = new FormData();
    form.append("file", audio, "voice.webm");
    return request<VoiceAskResponse>(`/api/voice/session/${sessionId}/audio`, { token, method: "POST", body: form });
  },
  askVoiceAudioStream: async (
    token: string,
    sessionId: string,
    audio: Blob,
    onEvent: (event: VoiceStreamEvent) => void,
    signal?: AbortSignal
  ): Promise<VoiceAskResponse> => {
    const form = new FormData();
    form.append("file", audio, "voice.webm");
    const response = await fetchWithRetry(`${API_BASE_URL}/api/voice/session/${sessionId}/audio/stream`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
      signal
    });
    return readVoiceStreamResponse(response, onEvent);
  },
  voiceSttStreamUrl: (token: string, sessionId: string) => {
    const url = new URL(`${websocketBaseUrl()}/api/voice/session/${sessionId}/stt/stream`);
    url.searchParams.set("token", token);
    return url.toString();
  },
  endVoiceSession: (token: string, sessionId: string) =>
    request<VoiceSession>(`/api/voice/session/${sessionId}/end`, { token, method: "POST" }),
  healthDetails: () => request<HealthDetails>("/health/details"),
  metrics: () => request<MetricsSnapshot>("/metrics/json")
};

async function readVoiceStreamResponse(
  response: Response,
  onEvent: (event: VoiceStreamEvent) => void
): Promise<VoiceAskResponse> {
    if (!response.ok || !response.body) {
      const error = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(error.error?.message || (typeof error.detail === "string" ? error.detail : VOICE_UNAVAILABLE_MESSAGE));
    }
    let finalEvent: VoiceAskResponse | null = null;
    await parseServerSentEvents(response.body, (event) => {
      onEvent(event);
      if (event.type === "error") {
        throw new Error(event.message);
      }
      if (event.type === "final") {
        finalEvent = event;
      }
    });
    if (!finalEvent) {
      throw new Error(VOICE_UNAVAILABLE_MESSAGE);
    }
    return finalEvent;
}

function websocketBaseUrl() {
  const url = new URL(API_BASE_URL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString().replace(/\/$/, "");
}

async function parseServerSentEvents(
  stream: ReadableStream<Uint8Array>,
  onEvent: (event: VoiceStreamEvent) => void
) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const data = part
        .split("\n")
        .find((line) => line.startsWith("data:"))
        ?.replace(/^data:\s*/, "");
      if (!data) continue;
      onEvent(JSON.parse(data) as VoiceStreamEvent);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    const data = buffer
      .split("\n")
      .find((line) => line.startsWith("data:"))
      ?.replace(/^data:\s*/, "");
    if (data) {
      onEvent(JSON.parse(data) as VoiceStreamEvent);
    }
  }
}
