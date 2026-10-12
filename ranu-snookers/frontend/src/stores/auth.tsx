/** Auth + branch context. Permissions come from the API (/auth/me); UI hides what
 * a user cannot do, but the backend re-checks every permission anyway. */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, post, refreshSession, tokenStore } from "@/services/api";
import type { Branch, Me, TokenOut } from "@/types/api";

interface AuthState {
  me: Me | null;
  ready: boolean;
  branch: Branch | null;
  branches: Branch[];
  setBranch: (b: Branch) => void;
  login: (identifier: string, password: string) => Promise<Me>;
  pinLogin: (username: string, pin: string) => Promise<Me>;
  register: (data: { name: string; phone: string; email?: string; password: string }) => Promise<Me>;
  logout: () => Promise<void>;
  can: (perm: string) => boolean;
  isStaff: boolean;
}

const Ctx = createContext<AuthState | null>(null);
const BRANCH_KEY = "ranu.branch";

function readBranchPref(): string | null {
  try {
    return localStorage.getItem(BRANCH_KEY);
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branch, setBranchState] = useState<Branch | null>(null);

  const loadMe = useCallback(async (): Promise<Me | null> => {
    try {
      const m = await api<Me>("/auth/me");
      setMe(m);
      const staff = m.permissions.some((p) => p !== "self.bookings");
      const list = staff ? await api<Branch[]>("/branches") : await api<Branch[]>("/public/branches", { auth: false });
      setBranches(list);
      const pref = readBranchPref();
      setBranchState(list.find((b) => b.id === pref) ?? list[0] ?? null);
      return m;
    } catch {
      setMe(null);
      return null;
    }
  }, []);

  useEffect(() => {
    let retry: ReturnType<typeof setTimeout> | undefined;
    const loadPublicBranches = async () => {
      try {
        const list = await api<Branch[]>("/public/branches", { auth: false });
        setBranches(list);
        setBranchState(list[0] ?? null);
      } catch {
        // Server unreachable: keep trying so pages fill in as soon as it is back.
        retry = setTimeout(loadPublicBranches, 5000);
      }
    };
    (async () => {
      if (await refreshSession()) await loadMe();
      else await loadPublicBranches();
      setReady(true);
    })();
    return () => clearTimeout(retry);
  }, [loadMe]);

  const finish = useCallback(async (t: TokenOut) => {
    tokenStore.set(t.access_token);
    const m = await loadMe();
    if (!m) throw new Error("Could not load profile");
    return m;
  }, [loadMe]);

  const value = useMemo<AuthState>(() => ({
    me, ready, branch, branches,
    setBranch: (b) => {
      setBranchState(b);
      try { localStorage.setItem(BRANCH_KEY, b.id); } catch { /* storage unavailable */ }
    },
    login: async (identifier, password) => finish(await post<TokenOut>("/auth/login", { identifier, password })),
    pinLogin: async (username, pin) => finish(await post<TokenOut>("/auth/pin-login", { username, pin })),
    register: async (data) => finish(await post<TokenOut>("/auth/register", data)),
    logout: async () => {
      try { await post("/auth/logout", {}); } catch { /* ignore */ }
      tokenStore.set(null);
      setMe(null);
    },
    can: (perm) => !!me?.permissions.includes(perm),
    isStaff: !!me?.permissions.some((p) => p !== "self.bookings"),
  }), [me, ready, branch, branches, finish]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
