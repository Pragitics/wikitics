import { DragEvent as ReactDragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUp,
  FileUp,
  LogOut,
  MessageSquarePlus,
  Mic,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Trash2
} from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../services/api";
import { useAuthStore } from "../stores/authStore";
import type { AskResponse, ConversationSummary, DocumentRecord, VoiceSession, VoiceStreamEvent, Workspace } from "../types/api";

type Notice = { kind: "error" | "info"; message: string } | null;
type UploadStage = "idle" | "uploading" | "preparing" | "ready" | "failed";
type AgentMode = "voice" | "chat";
type WorkspaceView = "chat" | "documents";
type VoiceState = "idle" | "listening" | "thinking" | "speaking";
type AuthMode = "login" | "register";
type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};
type StreamingAudioPlayer = {
  append: (chunk: Uint8Array) => void;
  finish: () => Promise<void>;
  stop: () => void;
};
type StreamingCapture = {
  stop: () => void;
};

const uploadSteps: Array<{ key: Exclude<UploadStage, "idle" | "failed">; label: string }> = [
  { key: "uploading", label: "Uploading" },
  { key: "preparing", label: "Preparing" },
  { key: "ready", label: "Ready" }
];

const acceptedFiles = ".pdf,.docx,.txt,.md,.markdown";
const maxDocumentsPerWorkspace = 5;
const speechThreshold = 0.025;
const silenceToSubmitMs = 1100;
const noSpeechRestartMs = 30000;
const maxUtteranceMs = 15000;
const bargeInDetectorOptions = {
  threshold: 0.045,
  holdMs: 260,
  graceMs: 650
};

export type BargeInDetectorState = {
  monitorStartedAt: number;
  speechStartedAt: number | null;
};

export function detectBargeInSpeech(
  state: BargeInDetectorState,
  volume: number,
  now: number,
  options = bargeInDetectorOptions
) {
  if (now - state.monitorStartedAt < options.graceMs) {
    state.speechStartedAt = null;
    return false;
  }
  if (volume < options.threshold) {
    state.speechStartedAt = null;
    return false;
  }
  state.speechStartedAt ??= now;
  return now - state.speechStartedAt >= options.holdMs;
}

export function floatToPcm16Base64(input: Float32Array, inputSampleRate: number, outputSampleRate = 16000) {
  if (!input.length || inputSampleRate <= 0 || outputSampleRate <= 0) return "";
  const ratio = inputSampleRate / outputSampleRate;
  const outputLength = Math.max(1, Math.floor(input.length / ratio));
  const bytes = new Uint8Array(outputLength * 2);
  const view = new DataView(bytes.buffer);
  for (let index = 0; index < outputLength; index += 1) {
    const sourceIndex = Math.min(input.length - 1, Math.floor(index * ratio));
    const sample = Math.max(-1, Math.min(1, input[sourceIndex]));
    const pcm = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
    view.setInt16(index * 2, pcm, true);
  }
  return bytesToBase64(bytes);
}

function bytesToBase64(bytes: Uint8Array) {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return window.btoa(binary);
}

export default function App() {
  const { token, user, workspaces, activeWorkspaceId, setSession, setWorkspaces, setActiveWorkspaceId, logout } =
    useAuthStore();
  const location = useLocation();
  const navigate = useNavigate();
  const [notice, setNotice] = useState<Notice>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [mode, setMode] = useState<AgentMode>("voice");
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>("chat");
  const [uploadStage, setUploadStage] = useState<UploadStage>("idle");
  const [selectedFileName, setSelectedFileName] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [hasDraftConversation, setHasDraftConversation] = useState(false);
  const [openWorkspaceMenuId, setOpenWorkspaceMenuId] = useState<string | null>(null);
  const [openConversationMenuId, setOpenConversationMenuId] = useState<string | null>(null);
  const [showWorkspaceCreator, setShowWorkspaceCreator] = useState(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [voiceSession, setVoiceSession] = useState<VoiceSession | null>(null);
  const [voiceState, setVoiceState] = useState<VoiceState>("idle");
  const [voiceActive, setVoiceActive] = useState(false);
  const [workspaceName, setWorkspaceName] = useState("");
  const [busy, setBusy] = useState(false);
  const [isDocumentDragActive, setIsDocumentDragActive] = useState(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const voiceActiveRef = useRef(false);
  const manualStopRef = useRef(false);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const streamingPlayerRef = useRef<StreamingAudioPlayer | null>(null);
  const speechResolveRef = useRef<(() => void) | null>(null);
  const voiceAbortRef = useRef<AbortController | null>(null);
  const bargeInFrameRef = useRef<number | null>(null);
  const streamingCaptureRef = useRef<StreamingCapture | null>(null);
  const documentDragDepthRef = useRef(0);

  const routeWorkspaceId = useMemo(() => {
    const match = location.pathname.match(/\/workspaces\/([^/]+)/);
    return match?.[1] || null;
  }, [location.pathname]);

  const activeWorkspace = useMemo(
    () => workspaces.find((workspace) => workspace.id === activeWorkspaceId) || null,
    [activeWorkspaceId, workspaces]
  );
  const hasReadyDocument = uploadStage === "ready" || documents.some((document) => document.status === "ready");

  useEffect(() => {
    if (!token) return;
    api
      .me(token)
      .then((currentUser) => setSession(token, currentUser))
      .then(() => api.workspaces(token))
      .then((nextWorkspaces) => {
        setWorkspaces(nextWorkspaces);
        const nextWorkspaceId = routeWorkspaceId || activeWorkspaceId || nextWorkspaces[0]?.id;
        if (nextWorkspaceId && !routeWorkspaceId) {
          navigate(`/workspaces/${nextWorkspaceId}`, { replace: true });
        }
      })
      .catch((error) => setNotice({ kind: "error", message: error instanceof Error ? error.message : "Login failed" }));
  }, [token, setSession, setWorkspaces, navigate, routeWorkspaceId, activeWorkspaceId]);

  useEffect(() => {
    if (!routeWorkspaceId || routeWorkspaceId === activeWorkspaceId) return;
    if (workspaces.some((workspace) => workspace.id === routeWorkspaceId)) {
      setActiveWorkspaceId(routeWorkspaceId);
    }
  }, [routeWorkspaceId, activeWorkspaceId, workspaces, setActiveWorkspaceId]);

  useEffect(() => {
    if (!token || !activeWorkspaceId) return;
    setDocuments([]);
    setMessages([]);
    setConversations([]);
    setConversationId(null);
    setHasDraftConversation(false);
    setOpenWorkspaceMenuId(null);
    setOpenConversationMenuId(null);
    setVoiceSession(null);
    voiceActiveRef.current = false;
    setVoiceActive(false);
    setVoiceState("idle");
    setMode("voice");
    setWorkspaceView("chat");
    setUploadStage("idle");
    setSelectedFileName("");
    setShowWorkspaceCreator(false);
    refreshWorkspaceData({ loadLatestConversation: true }).catch((error) =>
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Workspace failed" })
    );
  }, [token, activeWorkspaceId]);

  async function refreshWorkspaceData(options: { loadLatestConversation?: boolean } = {}): Promise<DocumentRecord[]> {
    if (!token || !activeWorkspaceId) return [];
    const [nextDocuments, nextConversations] = await Promise.all([
      api.documents(token, activeWorkspaceId),
      api.conversations(token, activeWorkspaceId).catch(() => [])
    ]);
    setDocuments(nextDocuments);
    setConversations(nextConversations);
    if ((options.loadLatestConversation || (!conversationId && messages.length === 0)) && nextConversations[0]) {
      await loadConversation(nextConversations[0].id);
    }
    return nextDocuments;
  }

  function refreshConversationListSoon() {
    if (!token || !activeWorkspaceId) return;
    const refresh = () => api.conversations(token, activeWorkspaceId).then(setConversations).catch(() => undefined);
    void refresh();
    window.setTimeout(() => void refresh(), 1400);
  }

  async function loadConversation(nextConversationId: string) {
    if (!token) return;
    const detail = await api.conversation(token, nextConversationId);
    setConversationId(detail.id);
    setHasDraftConversation(false);
    setWorkspaceView("chat");
    setMessages(
      detail.messages
        .filter((message) => message.role === "user" || message.role === "assistant")
        .map((message) => ({
          id: message.id,
          role: message.role as "user" | "assistant",
          content: message.content
        }))
    );
  }

  async function handleSelectConversation(nextConversationId: string) {
    setNotice(null);
    setOpenConversationMenuId(null);
    setMode("chat");
    try {
      await loadConversation(nextConversationId);
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Chat failed" });
    }
  }

  function handleNewConversation() {
    stopVoiceConversation();
    setShowWorkspaceCreator(false);
    setVoiceSession(null);
    setConversationId(null);
    setHasDraftConversation(true);
    setMessages([]);
    setOpenConversationMenuId(null);
    setWorkspaceView("chat");
    setMode(hasReadyDocument ? "voice" : "chat");
    setNotice(null);
  }

  async function handleDeleteConversation(nextConversationId: string) {
    if (!token) return;
    setBusy(true);
    setNotice(null);
    setOpenConversationMenuId(null);
    const nextConversation = conversations.find((conversation) => conversation.id !== nextConversationId) || null;
    try {
      await api.deleteConversation(token, nextConversationId);
      setConversations((items) => items.filter((conversation) => conversation.id !== nextConversationId));
      if (conversationId === nextConversationId) {
        stopVoiceConversation();
        setVoiceSession(null);
        setConversationId(null);
        setHasDraftConversation(false);
        setMessages([]);
        if (nextConversation) {
          await loadConversation(nextConversation.id);
        }
      }
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Delete failed" });
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteWorkspace(workspaceId: string) {
    if (!token) return;
    setBusy(true);
    setNotice(null);
    setOpenWorkspaceMenuId(null);
    try {
      await api.deleteWorkspace(token, workspaceId);
      const nextWorkspaces = workspaces.filter((workspace) => workspace.id !== workspaceId);
      setWorkspaces(nextWorkspaces);
      if (activeWorkspaceId === workspaceId) {
        stopVoiceConversation();
        setDocuments([]);
        setMessages([]);
        setConversations([]);
        setConversationId(null);
        setHasDraftConversation(false);
        setVoiceSession(null);
        setUploadStage("idle");
        const nextWorkspaceId = nextWorkspaces[0]?.id || null;
        setActiveWorkspaceId(nextWorkspaceId);
        navigate(nextWorkspaceId ? `/workspaces/${nextWorkspaceId}` : "/dashboard", { replace: true });
      }
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Delete failed" });
    } finally {
      setBusy(false);
    }
  }

  async function handleAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setNotice(null);
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") || "");
    const password = String(form.get("password") || "");
    const name = String(form.get("name") || "Wikitics User");
    try {
      const response =
        authMode === "register" ? await api.register(email, password, name) : await api.login(email, password);
      setSession(response.access_token, response.user);
      const nextWorkspaces = await api.workspaces(response.access_token);
      setWorkspaces(nextWorkspaces);
      const nextWorkspaceId = nextWorkspaces[0]?.id;
      navigate(nextWorkspaceId ? `/workspaces/${nextWorkspaceId}` : "/dashboard", { replace: true });
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Login failed" });
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !workspaceName.trim()) return;
    setBusy(true);
    setNotice(null);
    try {
      const created = await api.createWorkspace(token, workspaceName.trim());
      const nextWorkspaces = await api.workspaces(token).catch(() => upsertWorkspace(workspaces, created));
      setWorkspaces(nextWorkspaces);
      setActiveWorkspaceId(created.id);
      setWorkspaceName("");
      setShowWorkspaceCreator(false);
      navigate(`/workspaces/${created.id}`);
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Workspace failed" });
    } finally {
      setBusy(false);
    }
  }

  async function uploadAndProcessFiles(files: File[]) {
    if (!token || !activeWorkspaceId || busy) return;
    const availableSlots = Math.max(0, maxDocumentsPerWorkspace - documents.length);
    if (availableSlots <= 0) {
      setNotice({ kind: "error", message: `You can upload up to ${maxDocumentsPerWorkspace} documents in one workspace.` });
      return;
    }
    const filesToUpload = files.slice(0, availableSlots);
    if (!filesToUpload.length) return;
    if (files.length > availableSlots) {
      setNotice({ kind: "info", message: `Only ${availableSlots} more document${availableSlots === 1 ? "" : "s"} can be added.` });
    } else {
      setNotice(null);
    }
    stopVoiceConversation();
    setSelectedFileName(filesToUpload.length === 1 ? filesToUpload[0].name : `${filesToUpload.length} documents`);
    setUploadStage("uploading");
    setBusy(true);
    try {
      const uploadedDocuments: DocumentRecord[] = [];
      const processedDocuments: DocumentRecord[] = [];
      for (const file of filesToUpload) {
        const uploaded = await api.uploadDocument(token, activeWorkspaceId, file);
        uploadedDocuments.push(uploaded);
        setDocuments((items) => upsertDocument(items, uploaded));
      }
      setUploadStage("preparing");
      for (const uploaded of uploadedDocuments) {
        const processed = await api.processDocument(token, uploaded.id);
        processedDocuments.push(processed.document);
        setDocuments((items) => upsertDocument(items, processed.document));
      }
      const refreshedDocuments = await refreshWorkspaceData();
      if (!processedDocuments.every((processed) => refreshedDocuments.some((document) => document.id === processed.id))) {
        setDocuments((items) => processedDocuments.reduce((nextItems, document) => upsertDocument(nextItems, document), items));
      }
      setUploadStage("ready");
      setWorkspaceView("chat");
      setMode("voice");
    } catch (error) {
      setUploadStage("failed");
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Upload failed" });
    } finally {
      setBusy(false);
    }
  }

  async function handleUploadChange(event: FormEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const files = Array.from(input.files || []);
    if (!files.length) return;
    await uploadAndProcessFiles(files);
    input.value = "";
  }

  function handleDocumentDragEnter(event: ReactDragEvent<HTMLElement>) {
    if (!activeWorkspace || !dragEventHasFiles(event)) return;
    event.preventDefault();
    documentDragDepthRef.current += 1;
    setIsDocumentDragActive(true);
  }

  function handleDocumentDragOver(event: ReactDragEvent<HTMLElement>) {
    if (!activeWorkspace || !dragEventHasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = busy ? "none" : "copy";
  }

  function handleDocumentDragLeave(event: ReactDragEvent<HTMLElement>) {
    if (!activeWorkspace || !dragEventHasFiles(event)) return;
    event.preventDefault();
    documentDragDepthRef.current = Math.max(0, documentDragDepthRef.current - 1);
    if (documentDragDepthRef.current === 0) {
      setIsDocumentDragActive(false);
    }
  }

  function handleDocumentDrop(event: ReactDragEvent<HTMLElement>) {
    if (!activeWorkspace || !dragEventHasFiles(event)) return;
    event.preventDefault();
    documentDragDepthRef.current = 0;
    setIsDocumentDragActive(false);
    const files = Array.from(event.dataTransfer.files || []);
    if (files.length && !busy) {
      void uploadAndProcessFiles(files);
    }
  }

  async function handleQuestion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !activeWorkspaceId || !question.trim()) return;
    const prompt = question.trim();
    const userMessage = makeMessage("user", prompt);
    setQuestion("");
    setMessages((items) => [...items, userMessage]);
    setBusy(true);
    setNotice(null);
    try {
      const response = await api.ask(token, activeWorkspaceId, prompt, conversationId);
      applyAgentResponse(response);
      refreshConversationListSoon();
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Ask failed" });
    } finally {
      setBusy(false);
    }
  }

  async function ensureVoiceSession(): Promise<VoiceSession | null> {
    if (!token || !activeWorkspaceId) return null;
    if (voiceSession && voiceSession.status !== "ended") return voiceSession;
    setBusy(true);
    setNotice(null);
    try {
      const session = await api.createVoiceSession(token, activeWorkspaceId, conversationId);
      setVoiceSession(session);
      setConversationId(session.conversation_id);
      setHasDraftConversation(false);
      refreshConversationListSoon();
      return session;
    } catch (error) {
      setNotice({ kind: "error", message: error instanceof Error ? error.message : "Voice failed" });
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function handleMicClick() {
    if (!hasReadyDocument || (busy && !voiceActiveRef.current)) return;
    if (voiceActiveRef.current && voiceState === "speaking") {
      interruptAgentSpeech();
      return;
    }
    if (voiceActiveRef.current) {
      stopVoiceConversation();
      return;
    }
    await startVoiceConversation();
  }

  async function startVoiceConversation() {
    const session = await ensureVoiceSession();
    if (!session) return;
    if (!navigator.mediaDevices?.getUserMedia || (!window.MediaRecorder && !audioContextConstructor())) {
      setNotice({ kind: "error", message: "Mic unavailable" });
      setMode("chat");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });
      setupAudioMeter(stream);
      streamRef.current = stream;
      voiceActiveRef.current = true;
      manualStopRef.current = false;
      setVoiceActive(true);
      setNotice(null);
      startListeningSegment(session);
    } catch (error) {
      stopVoiceConversation();
      setNotice({ kind: "error", message: micErrorMessage(error) });
    }
  }

  function startListeningSegment(session: VoiceSession) {
    if (startStreamingListeningSegment(session)) return;
    startBlobListeningSegment(session);
  }

  function startBlobListeningSegment(session: VoiceSession) {
    if (!voiceActiveRef.current || !streamRef.current) return;
    if (recorderRef.current?.state === "recording") return;
    cancelMeterFrame();
    const stream = streamRef.current;
    let speechStarted = false;
    let lastSpeechAt = performance.now();
    const segmentStartedAt = performance.now();

    try {
      const mimeType = preferredAudioMimeType();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onerror = () => {
        stopVoiceConversation();
        setNotice({ kind: "error", message: "Mic failed" });
      };
      recorder.onstop = () => {
        cancelMeterFrame();
        const type = normalizeBrowserAudioType(recorder.mimeType || mimeType || "audio/webm");
        const audio = new Blob(chunksRef.current, { type });
        recorderRef.current = null;
        chunksRef.current = [];
        if (!voiceActiveRef.current || manualStopRef.current) {
          return;
        }
        if (!speechStarted || audio.size === 0) {
          startListeningSegment(session);
          return;
        }
        void submitVoiceAudio(audio, session);
      };
      setNotice(null);
      setVoiceState("listening");
      recorder.start(250);
      const checkSilence = () => {
        if (!voiceActiveRef.current || recorder.state !== "recording") return;
        const now = performance.now();
        const volume = currentMicVolume();
        if (volume > speechThreshold) {
          speechStarted = true;
          lastSpeechAt = now;
        }
        const hasFinishedUtterance = speechStarted && now - lastSpeechAt >= silenceToSubmitMs;
        const hasTimedOutWithoutSpeech = !speechStarted && now - segmentStartedAt >= noSpeechRestartMs;
        const hasReachedMaxUtterance = now - segmentStartedAt >= maxUtteranceMs;
        if (hasFinishedUtterance || hasTimedOutWithoutSpeech || hasReachedMaxUtterance) {
          recorder.stop();
          return;
        }
        animationFrameRef.current = window.requestAnimationFrame(checkSilence);
      };
      animationFrameRef.current = window.requestAnimationFrame(checkSilence);
    } catch (error) {
      stopVoiceConversation();
      setNotice({ kind: "error", message: micErrorMessage(error) });
    }
  }

  function startStreamingListeningSegment(session: VoiceSession) {
    if (!token || !voiceActiveRef.current || !streamRef.current || !audioContextRef.current || !("WebSocket" in window)) {
      return false;
    }
    const audioContext = audioContextRef.current;
    if (!audioContext.createScriptProcessor) return false;

    cancelMeterFrame();
    streamingCaptureRef.current?.stop();

    let speechStarted = false;
    let finalized = false;
    let fallbackStarted = false;
    let ignoreClose = false;
    let transcriptReceived = false;
    let lastSpeechAt = performance.now();
    const segmentStartedAt = performance.now();
    const queuedMessages: string[] = [];
    const websocket = new WebSocket(api.voiceSttStreamUrl(token, session.session_id));
    const source = audioContext.createMediaStreamSource(streamRef.current);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);

    const send = (payload: unknown) => {
      const encoded = JSON.stringify(payload);
      if (websocket.readyState === WebSocket.OPEN) {
        websocket.send(encoded);
        return;
      }
      queuedMessages.push(encoded);
    };
    const cleanup = () => {
      ignoreClose = true;
      cancelMeterFrame();
      processor.disconnect();
      source.disconnect();
      if (websocket.readyState === WebSocket.CONNECTING || websocket.readyState === WebSocket.OPEN) {
        websocket.close();
      }
      if (streamingCaptureRef.current?.stop === cleanup) {
        streamingCaptureRef.current = null;
      }
    };
    const fallbackToBlobCapture = () => {
      if (fallbackStarted) return;
      fallbackStarted = true;
      cleanup();
      if (voiceActiveRef.current && !manualStopRef.current) {
        startBlobListeningSegment(session);
      }
    };
    const finalize = () => {
      if (finalized) return;
      finalized = true;
      setVoiceState("thinking");
      send({ type: "flush" });
      window.setTimeout(() => {
        if (!transcriptReceived && voiceActiveRef.current && !manualStopRef.current) {
          fallbackToBlobCapture();
        }
      }, 3500);
    };

    streamingCaptureRef.current = { stop: cleanup };
    websocket.onopen = () => {
      while (queuedMessages.length > 0) {
        websocket.send(queuedMessages.shift() as string);
      }
    };
    websocket.onerror = fallbackToBlobCapture;
    websocket.onclose = () => {
      if (!ignoreClose && !finalized && voiceActiveRef.current && !manualStopRef.current) {
        fallbackToBlobCapture();
      }
    };
    websocket.onmessage = (event) => {
      let message: { type?: string; transcript?: string; message?: string };
      try {
        message = JSON.parse(String(event.data)) as { type?: string; transcript?: string; message?: string };
      } catch {
        fallbackToBlobCapture();
        return;
      }
      if (message.type === "speech_start") {
        speechStarted = true;
      }
      if (message.type === "error") {
        fallbackToBlobCapture();
        return;
      }
      if (message.type === "transcript" && message.transcript?.trim()) {
        transcriptReceived = true;
        cleanup();
        void submitVoiceTranscript(message.transcript.trim(), session);
      }
    };
    processor.onaudioprocess = (event) => {
      if (!voiceActiveRef.current || finalized) return;
      const input = event.inputBuffer.getChannelData(0);
      event.outputBuffer.getChannelData(0).fill(0);
      const audioBase64 = floatToPcm16Base64(input, audioContext.sampleRate, 16000);
      if (audioBase64) {
        send({ type: "audio", audio_base64: audioBase64, sample_rate: 16000, encoding: "pcm_s16le" });
      }
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
    void audioContext.resume?.();
    setNotice(null);
    setVoiceState("listening");

    const checkSilence = () => {
      if (!voiceActiveRef.current || finalized) return;
      const now = performance.now();
      const volume = currentMicVolume();
      if (volume > speechThreshold) {
        speechStarted = true;
        lastSpeechAt = now;
      }
      const hasFinishedUtterance = speechStarted && now - lastSpeechAt >= silenceToSubmitMs;
      const hasTimedOutWithoutSpeech = !speechStarted && now - segmentStartedAt >= noSpeechRestartMs;
      const hasReachedMaxUtterance = now - segmentStartedAt >= maxUtteranceMs;
      if (hasFinishedUtterance || hasReachedMaxUtterance) {
        finalize();
        return;
      }
      if (hasTimedOutWithoutSpeech) {
        cleanup();
        if (voiceActiveRef.current && !manualStopRef.current) {
          startListeningSegment(session);
        }
        return;
      }
      animationFrameRef.current = window.requestAnimationFrame(checkSilence);
    };
    animationFrameRef.current = window.requestAnimationFrame(checkSilence);
    return true;
  }

  function setupAudioMeter(stream: MediaStream) {
    const AudioContextClass = audioContextConstructor();
    if (!AudioContextClass) return;
    const audioContext = new AudioContextClass();
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 1024;
    audioContext.createMediaStreamSource(stream).connect(analyser);
    audioContextRef.current = audioContext;
    analyserRef.current = analyser;
  }

  function audioContextConstructor() {
    return window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  }

  function currentMicVolume() {
    const analyser = analyserRef.current;
    if (!analyser) return 1;
    const data = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (const value of data) {
      const centered = (value - 128) / 128;
      sum += centered * centered;
    }
    return Math.sqrt(sum / data.length);
  }

  function cancelMeterFrame() {
    if (animationFrameRef.current !== null) {
      window.cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
  }

  function cancelBargeInMonitor() {
    if (bargeInFrameRef.current !== null) {
      window.cancelAnimationFrame(bargeInFrameRef.current);
      bargeInFrameRef.current = null;
    }
  }

  function startBargeInMonitor(session: VoiceSession, onBargeIn: () => void) {
    if (!streamRef.current || !analyserRef.current) return;
    cancelBargeInMonitor();
    const detector: BargeInDetectorState = {
      monitorStartedAt: performance.now(),
      speechStartedAt: null
    };
    const checkBargeIn = () => {
      if (!voiceActiveRef.current || manualStopRef.current) return;
      const now = performance.now();
      if (detectBargeInSpeech(detector, currentMicVolume(), now)) {
        cancelBargeInMonitor();
        onBargeIn();
        interruptAgentSpeech();
        startListeningSegment(session);
        return;
      }
      bargeInFrameRef.current = window.requestAnimationFrame(checkBargeIn);
    };
    bargeInFrameRef.current = window.requestAnimationFrame(checkBargeIn);
  }

  function stopStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  function stopVoiceConversation() {
    voiceActiveRef.current = false;
    manualStopRef.current = true;
    setVoiceActive(false);
    cancelMeterFrame();
    cancelBargeInMonitor();
    streamingCaptureRef.current?.stop();
    streamingCaptureRef.current = null;
    voiceAbortRef.current?.abort();
    voiceAbortRef.current = null;
    stopAgentSpeech();
    const recorder = recorderRef.current;
    if (recorder?.state === "recording") {
      recorder.stop();
    }
    recorderRef.current = null;
    chunksRef.current = [];
    void audioContextRef.current?.close();
    audioContextRef.current = null;
    analyserRef.current = null;
    stopStream();
    setVoiceState("idle");
  }

  async function submitVoiceAudio(audio: Blob, session: VoiceSession) {
    if (!token) return;
    await submitVoiceTurn(session, (onEvent, signal) =>
      api.askVoiceAudioStream(token, session.session_id, audio, onEvent, signal)
    );
  }

  async function submitVoiceTranscript(transcript: string, session: VoiceSession) {
    if (!token) return;
    await submitVoiceTurn(session, (onEvent, signal) =>
      api.askVoiceTranscriptStream(token, session.session_id, transcript, onEvent, signal)
    );
  }

  async function submitVoiceTurn(
    session: VoiceSession,
    request: (onEvent: (event: VoiceStreamEvent) => void, signal: AbortSignal) => Promise<AskResponse & { transcript: string; audio_base64?: string; audio_mime?: string }>
  ) {
    if (!token) return;
    setVoiceState("thinking");
    setBusy(true);
    setNotice(null);
    let shouldListenAgain = false;
    const abortController = new AbortController();
    voiceAbortRef.current = abortController;
    try {
      const streamingPlayerHolder: { current: StreamingAudioPlayer | null } = { current: null };
      let answerAdded = false;
      let bargeInHandled = false;
      const response = await request(
        (event) => {
          if (event.type === "answer") {
            setConversationId(event.conversation_id);
            setHasDraftConversation(false);
            setMessages((items) => [
              ...items,
              makeMessage("user", event.transcript),
              makeMessage("assistant", event.answer)
            ]);
            answerAdded = true;
          }
          if (event.type === "audio_start" && voiceActiveRef.current) {
            streamingPlayerHolder.current = createStreamingAudioPlayer(event.audio_mime);
          }
          if (event.type === "audio_delta" && streamingPlayerHolder.current && voiceActiveRef.current) {
            streamingPlayerHolder.current.append(base64ToBytes(event.audio_base64));
          }
          if (event.type === "error") {
            throw new Error(event.message);
          }
        },
        abortController.signal
      );
      if (!answerAdded) {
        setConversationId(response.conversation_id);
        setHasDraftConversation(false);
        setMessages((items) => [
          ...items,
          makeMessage("user", response.transcript),
          makeMessage("assistant", response.answer)
        ]);
      }
      if (voiceActiveRef.current) {
        startBargeInMonitor(session, () => {
          bargeInHandled = true;
        });
        try {
          if (streamingPlayerHolder.current) {
            await streamingPlayerHolder.current.finish();
          } else {
            await speak(response.answer, response.audio_base64, response.audio_mime);
          }
        } finally {
          cancelBargeInMonitor();
        }
        refreshConversationListSoon();
        shouldListenAgain = voiceActiveRef.current && !bargeInHandled;
      }
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        shouldListenAgain = voiceActiveRef.current && !manualStopRef.current;
        return;
      }
      const message = error instanceof Error ? error.message : "Mic failed";
      if (message === "No speech detected" && voiceActiveRef.current) {
        shouldListenAgain = true;
        setNotice(null);
      } else {
        setVoiceState(voiceActiveRef.current ? "listening" : "idle");
        setNotice({ kind: "error", message });
      }
    } finally {
      if (voiceAbortRef.current === abortController) {
        voiceAbortRef.current = null;
      }
      setBusy(false);
      if (shouldListenAgain) {
        startListeningSegment(session);
      }
    }
  }

  function preferredAudioMimeType() {
    const options = ["audio/webm", "audio/mp4", "audio/ogg"];
    return options.find((type) => MediaRecorder.isTypeSupported(type)) || "";
  }

  function normalizeBrowserAudioType(type: string) {
    const normalized = type.split(";", 1)[0].trim().toLowerCase();
    if (normalized === "audio/mp4") return "audio/mp4";
    if (normalized === "audio/ogg") return "audio/ogg";
    return "audio/webm";
  }

  function micErrorMessage(error: unknown) {
    if (error instanceof DOMException) {
      if (["NotAllowedError", "SecurityError"].includes(error.name)) {
        return "Mic blocked";
      }
      if (["NotFoundError", "DevicesNotFoundError"].includes(error.name)) {
        return "Mic unavailable";
      }
    }
    return "Mic failed";
  }

  function applyAgentResponse(response: AskResponse) {
    setConversationId(response.conversation_id);
    setHasDraftConversation(false);
    setMessages((items) => [...items, makeMessage("assistant", response.answer)]);
  }

  function speak(answer: string, audioBase64?: string, audioMime = "audio/wav") {
    return new Promise<void>((resolve) => {
      speechResolveRef.current = () => {
        speechResolveRef.current = null;
        resolve();
      };
      const finish = () => {
        currentAudioRef.current = null;
        speechResolveRef.current?.();
      };
      if (audioBase64) {
        const audio = new Audio(base64AudioUrl(audioBase64, audioMime));
        currentAudioRef.current = audio;
        audio.onended = finish;
        audio.onerror = () => {
          currentAudioRef.current = null;
          speakWithBrowser(answer).then(() => speechResolveRef.current?.());
        };
        setVoiceState("speaking");
        audio.play().catch(() => {
          currentAudioRef.current = null;
          speakWithBrowser(answer).then(() => speechResolveRef.current?.());
        });
        return;
      }
      speakWithBrowser(answer).then(() => speechResolveRef.current?.());
    });
  }

  function speakWithBrowser(answer: string) {
    return new Promise<void>((resolve) => {
      if (!("speechSynthesis" in window) || !("SpeechSynthesisUtterance" in window)) {
        setVoiceState(voiceActiveRef.current ? "listening" : "idle");
        resolve();
        return;
      }
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(answer);
      utterance.onend = () => resolve();
      utterance.onerror = () => resolve();
      setVoiceState("speaking");
      window.speechSynthesis.speak(utterance);
    });
  }

  function stopBrowserSpeech() {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
  }

  function stopAgentSpeech() {
    const audio = currentAudioRef.current;
    cancelBargeInMonitor();
    streamingPlayerRef.current?.stop();
    streamingPlayerRef.current = null;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      currentAudioRef.current = null;
    }
    stopBrowserSpeech();
    speechResolveRef.current?.();
  }

  function interruptAgentSpeech() {
    cancelBargeInMonitor();
    voiceAbortRef.current?.abort();
    voiceAbortRef.current = null;
    stopAgentSpeech();
    setVoiceState("thinking");
  }

  function createStreamingAudioPlayer(audioMime: string): StreamingAudioPlayer {
    const chunks: Uint8Array[] = [];
    const MediaSourceClass = window.MediaSource;
    if (!MediaSourceClass || !MediaSourceClass.isTypeSupported(audioMime)) {
      return {
        append: (chunk) => chunks.push(chunk),
        finish: () => playAudioBlob(chunks, audioMime),
        stop: () => {
          chunks.length = 0;
        }
      };
    }

    const audio = new Audio();
    const mediaSource = new MediaSourceClass();
    const objectUrl = URL.createObjectURL(mediaSource);
    audio.src = objectUrl;
    currentAudioRef.current = audio;
    setVoiceState("speaking");

    let sourceBuffer: SourceBuffer | null = null;
    let finishRequested = false;
    let finishResolve: (() => void) | null = null;

    const cleanup = () => {
      if (currentAudioRef.current === audio) {
        currentAudioRef.current = null;
      }
      URL.revokeObjectURL(objectUrl);
      finishResolve?.();
    };
    const flush = () => {
      if (!sourceBuffer || sourceBuffer.updating) return;
      const next = chunks.shift();
      if (next) {
        sourceBuffer.appendBuffer(bytesToArrayBuffer(next));
        return;
      }
      if (finishRequested && mediaSource.readyState === "open") {
        mediaSource.endOfStream();
      }
    };
    mediaSource.addEventListener("sourceopen", () => {
      sourceBuffer = mediaSource.addSourceBuffer(audioMime);
      sourceBuffer.addEventListener("updateend", flush);
      audio.play().catch(() => undefined);
      flush();
    });
    audio.onended = cleanup;
    audio.onerror = cleanup;

    const player: StreamingAudioPlayer = {
      append: (chunk) => {
        chunks.push(chunk);
        flush();
      },
      finish: () =>
        new Promise<void>((resolve) => {
          finishResolve = resolve;
          finishRequested = true;
          flush();
        }),
      stop: () => {
        chunks.length = 0;
        if (mediaSource.readyState === "open") {
          try {
            mediaSource.endOfStream();
          } catch {
            // The media source may already be closing after an interruption.
          }
        }
        cleanup();
      }
    };
    streamingPlayerRef.current = player;
    return player;
  }

  function playAudioBlob(chunks: Uint8Array[], audioMime: string) {
    return new Promise<void>((resolve) => {
      if (!chunks.length) {
        resolve();
        return;
      }
      const audio = new Audio(URL.createObjectURL(new Blob(chunks.map(bytesToArrayBuffer), { type: audioMime })));
      const finish = () => {
        if (currentAudioRef.current === audio) {
          currentAudioRef.current = null;
        }
        if (speechResolveRef.current === finish) {
          speechResolveRef.current = null;
        }
        resolve();
      };
      speechResolveRef.current = finish;
      currentAudioRef.current = audio;
      audio.onended = finish;
      audio.onerror = finish;
      setVoiceState("speaking");
      audio.play().catch(finish);
    });
  }

  function base64AudioUrl(audioBase64: string, audioMime: string) {
    return `data:${audioMime};base64,${audioBase64}`;
  }

  function base64ToBytes(value: string) {
    const binary = window.atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
  }

  function bytesToArrayBuffer(bytes: Uint8Array) {
    const buffer = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(buffer).set(bytes);
    return buffer;
  }

  function handleLogout() {
    stopBrowserSpeech();
    stopVoiceConversation();
    logout();
    navigate("/login", { replace: true });
  }

  if (!token || !user) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-paper px-4 py-8">
        <form onSubmit={handleAuth} className="grid w-full max-w-sm gap-4 rounded-md border border-slate-200 bg-white p-6 shadow-sm">
          <h1 className="text-2xl font-semibold text-ink">Wikitics</h1>
          <div className="grid grid-cols-2 rounded-md bg-slate-100 p-1">
            <button
              type="button"
              className={authMode === "login" ? "auth-tab-active" : "auth-tab"}
              onClick={() => setAuthMode("login")}
            >
              Log in
            </button>
            <button
              type="button"
              className={authMode === "register" ? "auth-tab-active" : "auth-tab"}
              onClick={() => setAuthMode("register")}
            >
              Register
            </button>
          </div>
          {authMode === "register" && <input className="field" name="name" placeholder="Name" autoComplete="name" />}
          <input className="field" name="email" placeholder="Email" type="email" autoComplete="email" required />
          <input
            className="field"
            name="password"
            placeholder="Password"
            type="password"
            minLength={8}
            autoComplete={authMode === "register" ? "new-password" : "current-password"}
            required
          />
          <button className="command-button h-11" disabled={busy}>
            {authMode === "register" ? "Register" : "Log in"}
          </button>
          <NoticeView notice={notice} />
        </form>
      </main>
    );
  }

  const isProcessingDocument = uploadStage === "uploading" || uploadStage === "preparing";
  const showAgent = Boolean(!showWorkspaceCreator && activeWorkspace && workspaceView === "chat" && hasReadyDocument);

  return (
    <main
      data-testid="app-shell"
      className={`relative grid h-screen overflow-hidden bg-paper text-ink ${
        isSidebarCollapsed ? "lg:grid-cols-[72px_minmax(0,1fr)]" : "lg:grid-cols-[280px_minmax(0,1fr)]"
      }`}
      onClick={() => {
        setOpenWorkspaceMenuId(null);
        setOpenConversationMenuId(null);
      }}
      onDragEnter={handleDocumentDragEnter}
      onDragOver={handleDocumentDragOver}
      onDragLeave={handleDocumentDragLeave}
      onDrop={handleDocumentDrop}
    >
      {isDocumentDragActive && activeWorkspace && (
        <div className="document-drop-overlay" aria-hidden="true">
          <div className="document-drop-target">
            <FileUp size={34} />
            <span>{busy ? "Processing" : "Drop document"}</span>
          </div>
        </div>
      )}
      <aside className="border-b border-slate-200 bg-paper lg:h-screen lg:border-b-0 lg:border-r">
        <div className={isSidebarCollapsed ? "flex h-full flex-col items-center gap-4 p-3" : "flex h-full flex-col gap-7 p-4"}>
          <div className={isSidebarCollapsed ? "grid gap-3" : "flex items-center justify-between gap-2"}>
            <button
              className={isSidebarCollapsed ? "brand-button-collapsed" : "brand-text-button"}
              onClick={() => navigate("/dashboard")}
              title="Wikitics"
            >
              <span>{isSidebarCollapsed ? "W" : "Wikitics"}</span>
            </button>
            <button
              type="button"
              className="sidebar-collapse-button"
              onClick={() => setIsSidebarCollapsed((current) => !current)}
              title={isSidebarCollapsed ? "Open sidebar" : "Close sidebar"}
              aria-label={isSidebarCollapsed ? "Open sidebar" : "Close sidebar"}
            >
              {isSidebarCollapsed ? <PanelLeftOpen size={19} /> : <PanelLeftClose size={19} />}
            </button>
          </div>

          {!isSidebarCollapsed && (
          <nav className="min-h-0 flex-1">
            <button
              type="button"
              className="new-workspace-button"
              onClick={() => {
                setShowWorkspaceCreator(true);
                setWorkspaceName("");
                setNotice(null);
                stopVoiceConversation();
              }}
            >
              <Plus size={18} />
              <span>New workspace</span>
            </button>
            <div className="workspace-section-heading">Workspaces</div>
            <div className="scrollbar-soft max-h-[42vh] space-y-1 overflow-auto pr-1 lg:max-h-[calc(100vh-230px)]">
              {workspaces.map((workspace) => {
                const isActiveWorkspace = workspace.id === activeWorkspaceId;
                return (
                  <div key={workspace.id} className="workspace-tree-item">
                    <div className={`group ${isActiveWorkspace ? "workspace-row-active" : "workspace-row"}`}>
                      <button
                        className="workspace-title-button"
                        onClick={() => {
                          setOpenWorkspaceMenuId(null);
                          setShowWorkspaceCreator(false);
                          setActiveWorkspaceId(workspace.id);
                          navigate(`/workspaces/${workspace.id}`);
                        }}
                        title={workspace.name}
                      >
                        <span className="block w-full truncate">{workspace.name}</span>
                      </button>
                      <button
                        type="button"
                        className="workspace-menu-trigger"
                        onClick={(event) => {
                          event.stopPropagation();
                          setOpenWorkspaceMenuId((current) => (current === workspace.id ? null : workspace.id));
                        }}
                        title="Workspace options"
                        aria-label={`Workspace options for ${workspace.name}`}
                      >
                        <MoreHorizontal size={18} />
                      </button>
                      {openWorkspaceMenuId === workspace.id && (
                        <div className="workspace-menu" onClick={(event) => event.stopPropagation()}>
                          <button
                            type="button"
                            className="workspace-menu-danger"
                            onClick={() => void handleDeleteWorkspace(workspace.id)}
                            disabled={busy}
                          >
                            <Trash2 size={18} />
                            <span>Delete</span>
                          </button>
                        </div>
                      )}
                    </div>

                    {isActiveWorkspace && (
                      <div className="workspace-children">
                        <button
                          type="button"
                          className={workspaceView === "documents" ? "workspace-child-button-active" : "workspace-child-button"}
                          aria-label="Workspace documents"
                          onClick={() => {
                            setShowWorkspaceCreator(false);
                            setWorkspaceView("documents");
                          }}
                        >
                          <FileUp size={16} />
                          <span>Documents</span>
                        </button>
                        <button type="button" className="workspace-child-action" onClick={handleNewConversation}>
                          <MessageSquarePlus size={16} />
                          <span>New chat</span>
                        </button>

                        {(hasDraftConversation || conversations.length > 0) && (
                          <div className="workspace-conversation-list">
                            {hasDraftConversation && (
                              <div className="conversation-row-active">
                                <button className="conversation-title-button" onClick={handleNewConversation} title="New chat">
                                  <span className="block w-full truncate">New chat</span>
                                </button>
                              </div>
                            )}
                            {conversations.map((conversation) => (
                              <div
                                key={conversation.id}
                                className={`group ${conversation.id === conversationId ? "conversation-row-active" : "conversation-row"}`}
                              >
                                <button
                                  className="conversation-title-button"
                                  onClick={() => void handleSelectConversation(conversation.id)}
                                  title={conversationTitle(conversation)}
                                >
                                  <span className="block w-full truncate">{conversationTitle(conversation)}</span>
                                </button>
                                <button
                                  type="button"
                                  className="conversation-menu-trigger"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    setOpenConversationMenuId((current) => (current === conversation.id ? null : conversation.id));
                                  }}
                                  title="Conversation options"
                                  aria-label="Conversation options"
                                >
                                  <MoreHorizontal size={18} />
                                </button>
                                {openConversationMenuId === conversation.id && (
                                  <div className="conversation-menu" onClick={(event) => event.stopPropagation()}>
                                    <button
                                      type="button"
                                      className="conversation-menu-danger"
                                      onClick={() => void handleDeleteConversation(conversation.id)}
                                      disabled={busy}
                                    >
                                      <Trash2 size={18} />
                                      <span>Delete</span>
                                    </button>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </nav>
          )}

          {!isSidebarCollapsed && (
          <button className="sidebar-logout-button" onClick={handleLogout}>
            <LogOut size={18} />
            <span>Log out</span>
          </button>
          )}
        </div>
      </aside>

      <section className="grid h-screen min-h-0">
        <section className={showAgent ? "min-h-0 px-4 py-4 sm:px-6" : "grid min-h-0 place-items-center px-4 py-8"}>
          <div className={showAgent ? "h-full w-full" : "w-full max-w-3xl"}>
            {showWorkspaceCreator || !activeWorkspace ? (
              <WorkspaceStart
                busy={busy}
                workspaceName={workspaceName}
                setWorkspaceName={setWorkspaceName}
                onCreate={handleCreateWorkspace}
                notice={notice}
              />
            ) : showAgent ? (
              <AgentCenter
                busy={busy}
                mode={mode}
                setMode={setMode}
                uploadStage={uploadStage}
                selectedFileName={selectedFileName}
                isProcessingDocument={isProcessingDocument}
                voiceState={voiceState}
                voiceActive={voiceActive}
                messages={messages}
                question={question}
                setQuestion={setQuestion}
                onMicClick={handleMicClick}
                onQuestion={handleQuestion}
                notice={notice}
              />
            ) : (
              <UploadCenter
                busy={busy}
                uploadStage={uploadStage}
                selectedFileName={selectedFileName}
                onUploadChange={handleUploadChange}
                notice={notice}
              />
            )}
          </div>
        </section>
      </section>
    </main>
  );
}

function WorkspaceStart({
  busy,
  workspaceName,
  setWorkspaceName,
  onCreate,
  notice
}: {
  busy: boolean;
  workspaceName: string;
  setWorkspaceName: (value: string) => void;
  onCreate: (event: FormEvent<HTMLFormElement>) => void;
  notice: Notice;
}) {
  return (
    <form onSubmit={onCreate} className="mx-auto grid w-full max-w-lg gap-5 bg-white p-5">
      <input
        className="field"
        value={workspaceName}
        onChange={(event) => setWorkspaceName(event.target.value)}
        placeholder="Workspace name"
        aria-label="Workspace name"
      />
      <button className="command-button h-12 rounded-2xl" disabled={busy || !workspaceName.trim()}>
        Create
      </button>
      <NoticeView notice={notice} />
    </form>
  );
}

function UploadCenter({
  busy,
  uploadStage,
  selectedFileName,
  onUploadChange,
  notice
}: {
  busy: boolean;
  uploadStage: UploadStage;
  selectedFileName: string;
  onUploadChange: (event: FormEvent<HTMLInputElement>) => void;
  notice: Notice;
}) {
  return (
    <section className="animate-panel mx-auto grid max-w-xl gap-5">
      <label className={busy ? "upload-card upload-card-disabled" : "upload-card"} htmlFor="document-upload">
        <FileUp size={34} />
        <span className="text-lg font-semibold">{busy && selectedFileName ? selectedFileName : "Upload documents"}</span>
      </label>
      <input
        id="document-upload"
        className="sr-only"
        type="file"
        accept={acceptedFiles}
        multiple
        aria-label="Upload document"
        onChange={onUploadChange}
        disabled={busy}
      />
      {uploadStage !== "idle" && <ProgressStepper stage={uploadStage} />}
      <NoticeView notice={notice} />
    </section>
  );
}

function AgentCenter({
  busy,
  mode,
  setMode,
  uploadStage,
  selectedFileName,
  isProcessingDocument,
  voiceState,
  voiceActive,
  messages,
  question,
  setQuestion,
  onMicClick,
  onQuestion,
  notice
}: {
  busy: boolean;
  mode: AgentMode;
  setMode: (mode: AgentMode) => void;
  uploadStage: UploadStage;
  selectedFileName: string;
  isProcessingDocument: boolean;
  voiceState: VoiceState;
  voiceActive: boolean;
  messages: ChatMessage[];
  question: string;
  setQuestion: (value: string) => void;
  onMicClick: () => void;
  onQuestion: (event: FormEvent<HTMLFormElement>) => void;
  notice: Notice;
}) {
  return (
    <section className="agent-shell animate-panel">
      <div className="agent-toolbar">
        <div className="mode-toggle">
          <button type="button" className={mode === "voice" ? "auth-tab-active" : "auth-tab"} onClick={() => setMode("voice")}>
            Voice
          </button>
          <button type="button" className={mode === "chat" ? "auth-tab-active" : "auth-tab"} onClick={() => setMode("chat")}>
            Chat
          </button>
        </div>
      </div>

      <div className="agent-processing-slot">
        {isProcessingDocument && (
          <div className="agent-processing-panel" role="status">
            <span className="truncate text-sm font-semibold text-ink">{selectedFileName || "Document"}</span>
            <ProgressStepper stage={uploadStage} />
          </div>
        )}
      </div>

      {mode === "voice" ? (
        <div className="voice-canvas">
          <button
            className={`mic-button mic-button-${voiceState}`}
            onClick={onMicClick}
            disabled={busy && !voiceActive}
            aria-label={voiceActive ? "Stop voice" : "Start voice"}
            title={voiceActive ? "Stop voice" : "Start voice"}
          >
            <Mic size={64} strokeWidth={1.7} />
          </button>
          {voiceState !== "idle" && (
            <div className="voice-state" role="status">
              {formatVoiceState(voiceState)}
            </div>
          )}
        </div>
      ) : (
        <>
          <ChatTranscript messages={messages} />
          <ChatComposer
            busy={busy}
            question={question}
            setQuestion={setQuestion}
            onQuestion={onQuestion}
          />
        </>
      )}
      <NoticeView notice={notice} />
    </section>
  );
}

function ChatTranscript({ messages }: { messages: ChatMessage[] }) {
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript) return;
    transcript.scrollTop = transcript.scrollHeight;
  }, [messages]);

  return (
    <div ref={transcriptRef} className="chat-transcript scrollbar-soft">
      {messages.map((message) => (
        <div key={message.id} className={message.role === "user" ? "chat-row-user" : "chat-row-agent"}>
          <div className={message.role === "user" ? "chat-bubble-user" : "chat-bubble-agent"}>
            {renderMessageContent(message.content)}
          </div>
        </div>
      ))}
    </div>
  );
}

function renderMessageContent(content: string) {
  const parts = content.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return <span key={index}>{part}</span>;
  });
}

function ChatComposer({
  busy,
  question,
  setQuestion,
  onQuestion
}: {
  busy: boolean;
  question: string;
  setQuestion: (value: string) => void;
  onQuestion: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
  }, [question]);

  return (
    <form onSubmit={onQuestion} className="chat-composer">
      <textarea
        ref={textareaRef}
        className="chat-composer-input scrollbar-soft"
        value={question}
        onChange={(event) => setQuestion(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
        placeholder="Ask anything"
        aria-label="Ask"
        rows={1}
      />
      <button className="composer-send" disabled={busy || !question.trim()} title="Send">
        <ArrowUp size={22} strokeWidth={2.6} />
      </button>
    </form>
  );
}

function ProgressStepper({ stage }: { stage: UploadStage }) {
  const activeIndex = stage === "failed" ? 0 : uploadSteps.findIndex((step) => step.key === stage);
  return (
    <ol className="progress-stepper">
      {uploadSteps.map((step, index) => {
        const isDone = activeIndex >= index && stage !== "failed";
        const isCurrent = activeIndex === index && stage !== "failed";
        return (
          <li key={step.key} className={isDone ? "step-node-active" : "step-node"}>
            {index > 0 && <span className={activeIndex >= index ? "step-line-active" : "step-line"} />}
            <span className={isCurrent ? "step-dot-current" : isDone ? "step-dot-active" : "step-dot"}>{index + 1}</span>
            <span className={isDone ? "step-label-active" : "step-label"}>{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function NoticeView({ notice }: { notice: Notice }) {
  if (!notice) return null;
  return (
    <div className={notice.kind === "error" ? "notice-error" : "notice-info"} role={notice.kind === "error" ? "alert" : "status"}>
      {notice.message}
    </div>
  );
}

function dragEventHasFiles(event: ReactDragEvent<HTMLElement>) {
  return Array.from(event.dataTransfer.types || []).includes("Files");
}

function upsertWorkspace(workspaces: Workspace[], workspace: Workspace) {
  return [workspace, ...workspaces.filter((item) => item.id !== workspace.id)];
}

function upsertDocument(documents: DocumentRecord[], document: DocumentRecord) {
  return [document, ...documents.filter((item) => item.id !== document.id)];
}

function conversationTitle(conversation: ConversationSummary) {
  const title = conversation.title?.trim();
  if (title) return title;
  return conversation.mode === "voice" ? "Voice chat" : "New chat";
}

function makeMessage(role: ChatMessage["role"], content: string): ChatMessage {
  return {
    id: `${role}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    role,
    content
  };
}

function formatVoiceState(state: VoiceState) {
  return state.charAt(0).toUpperCase() + state.slice(1);
}
