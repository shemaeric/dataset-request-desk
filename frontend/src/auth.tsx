import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Navigate, Outlet } from "react-router-dom";
import { currentUser, login as loginRequest, logout as logoutRequest, setUnauthorizedHandler } from "./api";
import { ApiError, type User } from "./types";

type AuthStatus =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "ready"; user: User }
  | { status: "error"; message: string };

type AuthValue = {
  state: AuthStatus;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

function failureMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return "Could not reach the API";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthStatus>({ status: "loading" });

  async function refresh(): Promise<void> {
    setState({ status: "loading" });
    try {
      const user = await currentUser();
      setState({ status: "ready", user });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setState({ status: "anonymous" });
        return;
      }
      setState({ status: "error", message: failureMessage(error) });
    }
  }

  useEffect(() => {
    let cancelled = false;
    setUnauthorizedHandler(() => {
      if (!cancelled) {
        setState({ status: "anonymous" });
      }
    });

    currentUser()
      .then((user) => {
        if (!cancelled) {
          setState({ status: "ready", user });
        }
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        if (error instanceof ApiError && error.status === 401) {
          setState({ status: "anonymous" });
          return;
        }
        setState({ status: "error", message: failureMessage(error) });
      });

    return () => {
      cancelled = true;
      setUnauthorizedHandler(null);
    };
  }, []);

  async function login(email: string, password: string): Promise<void> {
    const user = await loginRequest(email, password);
    setState({ status: "ready", user });
  }

  async function logout(): Promise<void> {
    await logoutRequest();
    setState({ status: "anonymous" });
  }

  return (
    <AuthContext.Provider value={{ state, login, logout, refresh }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("AuthProvider is missing");
  }
  return value;
}

export function RequireAuth() {
  const { state, refresh } = useAuth();

  if (state.status === "loading") {
    return <p className="status">Checking session</p>;
  }
  if (state.status === "error") {
    return (
      <main className="shell">
        <p className="form-error" role="alert">
          {state.message}
        </p>
        <button type="button" onClick={() => void refresh()}>
          Try again
        </button>
      </main>
    );
  }
  if (state.status === "anonymous") {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}
