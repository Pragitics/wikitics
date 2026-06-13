import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App, { detectBargeInSpeech, floatToPcm16Base64 } from "./App";
import { api } from "../services/api";

const storeFns = vi.hoisted(() => ({
  setSession: vi.fn(),
  setWorkspaces: vi.fn(),
  setActiveWorkspaceId: vi.fn(),
  logout: vi.fn()
}));

const authState = vi.hoisted(() => ({
  token: "token-1" as string | null,
  user: { id: "user-1", email: "owner@example.com", name: "Owner" } as { id: string; email: string; name: string } | null,
  workspaces: [{ id: "workspace-1", name: "Default", owner_id: "user-1" }],
  activeWorkspaceId: "workspace-1" as string | null
}));

vi.mock("../stores/authStore", () => ({
  useAuthStore: () => ({
    ...authState,
    ...storeFns
  })
}));

vi.mock("../services/api", () => ({
  api: {
    register: vi.fn(),
    login: vi.fn(),
    me: vi.fn(),
    workspaces: vi.fn(),
    createWorkspace: vi.fn(),
    deleteWorkspace: vi.fn(),
    documents: vi.fn(),
    conversations: vi.fn(),
    conversation: vi.fn(),
    deleteConversation: vi.fn(),
    uploadDocument: vi.fn(),
    processDocument: vi.fn(),
    ask: vi.fn(),
    createVoiceSession: vi.fn(),
    askVoice: vi.fn(),
    askVoiceTranscriptStream: vi.fn(),
    askVoiceAudio: vi.fn(),
    askVoiceAudioStream: vi.fn(),
    voiceSttStreamUrl: vi.fn(),
    endVoiceSession: vi.fn()
  }
}));

const mockedApi = vi.mocked(api);

describe("App", () => {
  afterEach(() => {
    cleanup();
    Reflect.deleteProperty(window, "SpeechRecognition");
    Reflect.deleteProperty(window, "webkitSpeechRecognition");
    Reflect.deleteProperty(window, "MediaRecorder");
    Reflect.deleteProperty(window, "AudioContext");
    Reflect.deleteProperty(navigator, "mediaDevices");
  });

  beforeEach(() => {
    vi.clearAllMocks();
    authState.token = "token-1";
    authState.user = { id: "user-1", email: "owner@example.com", name: "Owner" };
    authState.workspaces = [{ id: "workspace-1", name: "Default", owner_id: "user-1" }];
    authState.activeWorkspaceId = "workspace-1";
    mockedApi.me.mockResolvedValue({ id: "user-1", email: "owner@example.com", name: "Owner" });
    mockedApi.workspaces.mockResolvedValue([{ id: "workspace-1", name: "Default", owner_id: "user-1" }]);
    mockedApi.deleteWorkspace.mockResolvedValue({ deleted: true, workspace_id: "workspace-1" });
    mockedApi.documents.mockResolvedValue([]);
    mockedApi.conversations.mockResolvedValue([]);
    mockedApi.conversation.mockResolvedValue({
      id: "conv-1",
      workspace_id: "workspace-1",
      user_id: "user-1",
      mode: "text",
      messages: []
    });
    mockedApi.deleteConversation.mockResolvedValue({ deleted: true, conversation_id: "conv-1" });
  });

  it("submits the login form", async () => {
    authState.token = null;
    authState.user = null;
    authState.workspaces = [];
    authState.activeWorkspaceId = null;
    mockedApi.login.mockResolvedValue({
      access_token: "token-2",
      user: { id: "user-2", email: "user@example.com", name: "User" }
    });
    mockedApi.workspaces.mockResolvedValue([{ id: "workspace-2", name: "Workspace", owner_id: "user-2" }]);
    renderApp("/login");

    fireEvent.change(screen.getByPlaceholderText("Email"), { target: { value: "user@example.com" } });
    fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "password123" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Log in" })[1]);

    await waitFor(() => expect(mockedApi.login).toHaveBeenCalledWith("user@example.com", "password123"));
    expect(storeFns.setSession).toHaveBeenCalled();
    expect(storeFns.setWorkspaces).toHaveBeenCalled();
  });

  it("creates a workspace", async () => {
    authState.workspaces = [];
    authState.activeWorkspaceId = null;
    mockedApi.workspaces.mockResolvedValue([]);
    mockedApi.createWorkspace.mockResolvedValue({ id: "workspace-2", name: "Softrate", owner_id: "user-1" });
    renderApp("/dashboard");

    fireEvent.change(screen.getAllByLabelText("Workspace name")[0], { target: { value: "Softrate" } });
    fireEvent.submit(screen.getAllByLabelText("Workspace name")[0].closest("form") as HTMLFormElement);

    await waitFor(() => expect(mockedApi.createWorkspace).toHaveBeenCalledWith("token-1", "Softrate"));
    expect(storeFns.setActiveWorkspaceId).toHaveBeenCalledWith("workspace-2");
  });

  it("opens workspace creation on the main screen when workspaces already exist", async () => {
    authState.workspaces = [{ id: "workspace-1", name: "Default", owner_id: "user-1" }];
    authState.activeWorkspaceId = "workspace-1";
    mockedApi.workspaces.mockResolvedValue(authState.workspaces);
    mockedApi.createWorkspace.mockResolvedValue({ id: "workspace-2", name: "Client", owner_id: "user-1" });
    renderApp();

    fireEvent.click(await screen.findByRole("button", { name: "New workspace" }));
    fireEvent.change(screen.getByLabelText("Workspace name"), { target: { value: "Client" } });
    fireEvent.submit(screen.getByLabelText("Workspace name").closest("form") as HTMLFormElement);

    await waitFor(() => expect(mockedApi.createWorkspace).toHaveBeenCalledWith("token-1", "Client"));
    expect(storeFns.setActiveWorkspaceId).toHaveBeenCalledWith("workspace-2");
  });

  it("deletes a workspace from the sidebar menu", async () => {
    authState.workspaces = [
      { id: "workspace-1", name: "Default", owner_id: "user-1" },
      { id: "workspace-2", name: "Archive", owner_id: "user-1" }
    ];
    authState.activeWorkspaceId = "workspace-1";
    mockedApi.workspaces.mockResolvedValue(authState.workspaces);
    mockedApi.deleteWorkspace.mockResolvedValue({ deleted: true, workspace_id: "workspace-1" });
    renderApp();

    fireEvent.click(await screen.findByLabelText("Workspace options for Default"));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(mockedApi.deleteWorkspace).toHaveBeenCalledWith("token-1", "workspace-1"));
    expect(storeFns.setWorkspaces).toHaveBeenCalledWith([{ id: "workspace-2", name: "Archive", owner_id: "user-1" }]);
    expect(storeFns.setActiveWorkspaceId).toHaveBeenCalledWith("workspace-2");
  });

  it("uploads and prepares a document", async () => {
    mockedApi.uploadDocument.mockResolvedValue({
      id: "doc-1",
      workspace_id: "workspace-1",
      filename: "policy.txt",
      file_type: "txt",
      status: "uploaded"
    });
    mockedApi.processDocument.mockResolvedValue({
      document: { id: "doc-1", workspace_id: "workspace-1", filename: "policy.txt", file_type: "txt", status: "ready" },
      chunk_count: 2
    });
    renderApp();

    const input = screen.getByLabelText("Upload document") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["policy"], "policy.txt", { type: "text/plain" })] } });

    await waitFor(() => expect(mockedApi.uploadDocument).toHaveBeenCalledWith("token-1", "workspace-1", expect.any(File)));
    expect(mockedApi.processDocument).toHaveBeenCalledWith("token-1", "doc-1");
    await screen.findByRole("button", { name: "Start voice" });
  });

  it("shows workspace children and active workspace conversations in the sidebar", async () => {
    mockedApi.documents.mockResolvedValue([
      { id: "doc-1", workspace_id: "workspace-1", filename: "policy.txt", file_type: "txt", status: "ready" }
    ]);
    mockedApi.conversations.mockResolvedValue([
      {
        id: "conv-1",
        workspace_id: "workspace-1",
        user_id: "user-1",
        mode: "text",
        title: "Policy chat",
        message_count: 2,
        created_at: "2026-05-24T00:00:00Z",
        updated_at: "2026-05-24T00:00:00Z"
      }
    ]);
    renderApp();

    await screen.findByLabelText("Upload documents");
    expect(screen.queryByLabelText("Workspace chat")).toBeNull();
    expect(screen.queryByLabelText("Workspace conversations")).toBeNull();
    expect(screen.getByText("Policy chat")).toBeTruthy();
  });

  it("shows a draft chat row when starting a new chat", async () => {
    mockedApi.documents.mockResolvedValue([
      { id: "doc-1", workspace_id: "workspace-1", filename: "policy.txt", file_type: "txt", status: "ready" }
    ]);
    renderApp();

    fireEvent.click(await screen.findByRole("button", { name: "New chat" }));

    expect(screen.getAllByText("New chat").length).toBeGreaterThan(1);
  });

  it("adds another document from upload documents navigation", async () => {
    let finishProcessing!: (value: {
      document: { id: string; workspace_id: string; filename: string; file_type: string; status: string };
      chunk_count: number;
    }) => void;
    mockedApi.documents.mockResolvedValue([
      { id: "doc-1", workspace_id: "workspace-1", filename: "policy.txt", file_type: "txt", status: "ready" }
    ]);
    mockedApi.uploadDocument.mockResolvedValue({
      id: "doc-2",
      workspace_id: "workspace-1",
      filename: "invoice.txt",
      file_type: "txt",
      status: "uploaded"
    });
    mockedApi.processDocument.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishProcessing = resolve;
        })
    );
    renderApp();

    fireEvent.click(await screen.findByLabelText("Upload documents"));
    const input = (await screen.findByLabelText("Upload document")) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["invoice"], "invoice.txt", { type: "text/plain" })] } });

    await screen.findByText("Preparing");
    expect(mockedApi.uploadDocument).toHaveBeenCalledWith("token-1", "workspace-1", expect.any(File));
    finishProcessing({
      document: { id: "doc-2", workspace_id: "workspace-1", filename: "invoice.txt", file_type: "txt", status: "ready" },
      chunk_count: 3
    });
    await waitFor(() => expect(mockedApi.processDocument).toHaveBeenCalledWith("token-1", "doc-2"));
  });

  it("uploads multiple documents from upload documents navigation up to the workspace limit", async () => {
    mockedApi.documents.mockResolvedValue([
      { id: "doc-1", workspace_id: "workspace-1", filename: "policy.txt", file_type: "txt", status: "ready" }
    ]);
    mockedApi.uploadDocument.mockImplementation((_token, _workspaceId, file: File) =>
      Promise.resolve({
        id: file.name === "invoice.txt" ? "doc-2" : "doc-3",
        workspace_id: "workspace-1",
        filename: file.name,
        file_type: "txt",
        status: "uploaded"
      })
    );
    mockedApi.processDocument.mockImplementation((_token, documentId: string) =>
      Promise.resolve({
        document: {
          id: documentId,
          workspace_id: "workspace-1",
          filename: documentId === "doc-2" ? "invoice.txt" : "support.txt",
          file_type: "txt",
          status: "ready"
        },
        chunk_count: 3
      })
    );
    renderApp();

    fireEvent.click(await screen.findByLabelText("Upload documents"));
    const input = (await screen.findByLabelText("Upload document")) as HTMLInputElement;
    expect(input.multiple).toBe(true);
    fireEvent.change(input, {
      target: {
        files: [
          new File(["invoice"], "invoice.txt", { type: "text/plain" }),
          new File(["support"], "support.txt", { type: "text/plain" })
        ]
      }
    });

    await waitFor(() => expect(mockedApi.uploadDocument).toHaveBeenCalledTimes(2));
    expect(mockedApi.processDocument).toHaveBeenCalledWith("token-1", "doc-2");
    expect(mockedApi.processDocument).toHaveBeenCalledWith("token-1", "doc-3");
  });

  it("accepts a document drop before the first conversation starts", async () => {
    let finishProcessing!: (value: {
      document: { id: string; workspace_id: string; filename: string; file_type: string; status: string };
      chunk_count: number;
    }) => void;
    mockedApi.uploadDocument.mockResolvedValue({
      id: "doc-1",
      workspace_id: "workspace-1",
      filename: "policy.txt",
      file_type: "txt",
      status: "uploaded"
    });
    mockedApi.processDocument.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishProcessing = resolve;
        })
    );
    renderApp();

    const file = new File(["policy"], "policy.txt", { type: "text/plain" });
    const shell = screen.getByTestId("app-shell");
    fireEvent.dragEnter(shell, { dataTransfer: { types: ["Files"], files: [file] } });
    fireEvent.drop(shell, { dataTransfer: { types: ["Files"], files: [file] } });

    await screen.findByText("Preparing");
    expect(mockedApi.uploadDocument).toHaveBeenCalledWith("token-1", "workspace-1", expect.any(File));
    finishProcessing({
      document: { id: "doc-1", workspace_id: "workspace-1", filename: "policy.txt", file_type: "txt", status: "ready" },
      chunk_count: 2
    });
    await screen.findByRole("button", { name: "Start voice" });
  });

  it("submits a chat question", async () => {
    mockedApi.documents.mockResolvedValue([
      { id: "doc-1", workspace_id: "workspace-1", filename: "policy.txt", file_type: "txt", status: "ready" }
    ]);
    mockedApi.ask.mockResolvedValue({
      answer: "The penalty is 2 percent.",
      conversation_id: "conv-1",
      message_id: "msg-1",
      citations: []
    });
    renderApp();

    fireEvent.click(await screen.findByRole("button", { name: "Chat" }));
    fireEvent.change(screen.getByLabelText("Ask"), { target: { value: "Penalty?" } });
    fireEvent.click(screen.getByTitle("Send"));

    await screen.findByText("The penalty is 2 percent.");
    expect(mockedApi.ask).toHaveBeenCalledWith("token-1", "workspace-1", "Penalty?", null);
  });

  it("loads stored conversation history", async () => {
    mockedApi.documents.mockResolvedValue([
      { id: "doc-1", workspace_id: "workspace-1", filename: "policy.txt", file_type: "txt", status: "ready" }
    ]);
    mockedApi.conversations.mockResolvedValue([
      {
        id: "conv-1",
        workspace_id: "workspace-1",
        user_id: "user-1",
        mode: "text",
        created_at: "2026-05-24T00:00:00Z",
        updated_at: "2026-05-24T00:00:00Z"
      }
    ]);
    mockedApi.conversation.mockResolvedValue({
      id: "conv-1",
      workspace_id: "workspace-1",
      user_id: "user-1",
      mode: "text",
      messages: [
        { id: "msg-1", role: "user", content: "Old question", created_at: "2026-05-24T00:00:00Z" },
        { id: "msg-2", role: "assistant", content: "Old answer", created_at: "2026-05-24T00:00:01Z" }
      ]
    });
    renderApp();

    fireEvent.click(await screen.findByRole("button", { name: "Chat" }));

    await screen.findByText("Old question");
    await screen.findByText("Old answer");
    expect(mockedApi.conversation).toHaveBeenCalledWith("token-1", "conv-1");
  });

  it("deletes a stored conversation from the sidebar menu", async () => {
    mockedApi.documents.mockResolvedValue([
      { id: "doc-1", workspace_id: "workspace-1", filename: "policy.txt", file_type: "txt", status: "ready" }
    ]);
    mockedApi.conversations.mockResolvedValue([
      {
        id: "conv-1",
        workspace_id: "workspace-1",
        user_id: "user-1",
        mode: "text",
        title: "Old question",
        message_count: 2,
        created_at: "2026-05-24T00:00:00Z",
        updated_at: "2026-05-24T00:00:00Z"
      }
    ]);
    mockedApi.conversation.mockResolvedValue({
      id: "conv-1",
      workspace_id: "workspace-1",
      user_id: "user-1",
      mode: "text",
      messages: [
        { id: "msg-1", role: "user", content: "Old question", created_at: "2026-05-24T00:00:00Z" },
        { id: "msg-2", role: "assistant", content: "Old answer", created_at: "2026-05-24T00:00:01Z" }
      ]
    });
    renderApp();

    fireEvent.click(await screen.findByLabelText("Conversation options"));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(mockedApi.deleteConversation).toHaveBeenCalledWith("token-1", "conv-1"));
  });

  it("detects only sustained speech for voice barge-in", () => {
    const state = { monitorStartedAt: 0, speechStartedAt: null };
    const options = { threshold: 0.05, graceMs: 650, holdMs: 250 };

    expect(detectBargeInSpeech(state, 0.12, 500, options)).toBe(false);
    expect(state.speechStartedAt).toBeNull();
    expect(detectBargeInSpeech(state, 0.12, 700, options)).toBe(false);
    expect(detectBargeInSpeech(state, 0.01, 820, options)).toBe(false);
    expect(state.speechStartedAt).toBeNull();
    expect(detectBargeInSpeech(state, 0.12, 900, options)).toBe(false);
    expect(detectBargeInSpeech(state, 0.12, 1160, options)).toBe(true);
  });

  it("encodes browser audio samples as little-endian PCM16", () => {
    const encoded = floatToPcm16Base64(new Float32Array([-1, 0, 1]), 16000, 16000);
    const bytes = Uint8Array.from(window.atob(encoded), (char) => char.charCodeAt(0));

    expect(Array.from(bytes)).toEqual([0, 128, 0, 0, 255, 127]);
  });

  it("starts a voice ask flow", async () => {
    let recorderStarts = 0;
    class FakeMediaRecorder {
      static isTypeSupported() {
        return true;
      }

      mimeType = "audio/webm";
      state: RecordingState = "inactive";
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onend: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onstop: (() => void) | null = null;

      start() {
        this.state = "recording";
        if (recorderStarts === 0) {
          recorderStarts += 1;
          window.setTimeout(() => this.stop(), 20);
        }
        return undefined;
      }

      stop() {
        if (this.state === "inactive") return;
        this.state = "inactive";
        this.ondataavailable?.({ data: new Blob(["voice"], { type: "audio/webm" }) } as BlobEvent);
        this.onstop?.();
      }
    }
    class FakeAnalyser {
      fftSize = 1024;
      calls = 0;

      getByteTimeDomainData(data: Uint8Array) {
        this.calls += 1;
        data.fill(this.calls === 1 ? 255 : 128);
      }
    }
    class FakeAudioContext {
      analyser = new FakeAnalyser();

      createAnalyser() {
        return this.analyser;
      }

      createMediaStreamSource() {
        return { connect: vi.fn() };
      }

      close() {
        return Promise.resolve();
      }
    }
    Object.defineProperty(window, "MediaRecorder", { value: FakeMediaRecorder, configurable: true });
    Object.defineProperty(window, "AudioContext", { value: FakeAudioContext, configurable: true });
    const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] });
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia },
      configurable: true
    });
    mockedApi.documents.mockResolvedValue([
      { id: "doc-1", workspace_id: "workspace-1", filename: "policy.txt", file_type: "txt", status: "ready" }
    ]);
    mockedApi.createVoiceSession.mockResolvedValue({
      session_id: "voice-1",
      conversation_id: "conv-1",
      room_name: "room-1",
      livekit_url: "http://livekit",
      status: "active"
    });
    mockedApi.voiceSttStreamUrl.mockReturnValue("ws://localhost/stt");
    mockedApi.askVoiceAudioStream.mockImplementation(async (_token, _sessionId, _audio, onEvent) => {
      onEvent({
        type: "answer",
        answer: "The penalty is 2 percent.",
        transcript: "Penalty?",
        conversation_id: "conv-1",
        message_id: "msg-1"
      });
      return {
        answer: "The penalty is 2 percent.",
        transcript: "Penalty?",
        audio_bytes: 0,
        conversation_id: "conv-1",
        message_id: "msg-1",
        citations: []
      };
    });
    mockedApi.askVoiceAudio.mockResolvedValue({
      answer: "The penalty is 2 percent.",
      transcript: "Penalty?",
      audio_bytes: 0,
      conversation_id: "conv-1",
      message_id: "msg-1",
      citations: []
    });
    renderApp();

    fireEvent.click(await screen.findByRole("button", { name: "Start voice" }));

    await waitFor(() => expect(mockedApi.createVoiceSession).toHaveBeenCalledWith("token-1", "workspace-1", null));
    expect(getUserMedia).toHaveBeenCalledWith({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });
    await waitFor(() =>
      expect(mockedApi.askVoiceAudioStream).toHaveBeenCalledWith(
        "token-1",
        "voice-1",
        expect.any(Blob),
        expect.any(Function),
        expect.any(AbortSignal)
      )
    );
    fireEvent.click(await screen.findByRole("button", { name: "Stop voice" }));
    fireEvent.click(await screen.findByRole("button", { name: "Chat" }));
    await screen.findByText("The penalty is 2 percent.");
  });
});

function renderApp(path = "/workspaces/workspace-1") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>
  );
}
