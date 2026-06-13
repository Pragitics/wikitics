import { create } from "zustand";
import type { User, Workspace } from "../types/api";

type AuthState = {
  token: string | null;
  user: User | null;
  workspaces: Workspace[];
  activeWorkspaceId: string | null;
  setSession: (token: string, user: User) => void;
  setWorkspaces: (workspaces: Workspace[]) => void;
  setActiveWorkspaceId: (workspaceId: string | null) => void;
  logout: () => void;
};

const storedToken = localStorage.getItem("wikitics_token");

export const useAuthStore = create<AuthState>((set) => ({
  token: storedToken,
  user: null,
  workspaces: [],
  activeWorkspaceId: null,
  setSession: (token, user) => {
    localStorage.setItem("wikitics_token", token);
    set({ token, user });
  },
  setWorkspaces: (workspaces) =>
    set((state) => ({
      workspaces,
      activeWorkspaceId: state.activeWorkspaceId || workspaces[0]?.id || null
    })),
  setActiveWorkspaceId: (workspaceId) => set({ activeWorkspaceId: workspaceId }),
  logout: () => {
    localStorage.removeItem("wikitics_token");
    set({ token: null, user: null, workspaces: [], activeWorkspaceId: null });
  }
}));
