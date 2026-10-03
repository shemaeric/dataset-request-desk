import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { failureMessage } from "./api";
import { useAuth } from "./auth";
import type { Role } from "./types";

const roleLabel: Record<Role, string> = {
  client: "Client",
  operator: "Operator",
  admin: "Admin",
};

export function Frame({ children }: { children: ReactNode }) {
  const { state, logout } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const user = state.status === "ready" ? state.user : null;

  async function onLogout() {
    setError(null);
    setPending(true);
    try {
      await logout();
    } catch (caught) {
      setError(failureMessage(caught));
      setPending(false);
    }
  }

  return (
    <div className={user ? `desk desk-${user.role}` : "desk"}>
      <header className="desk-bar">
        <Link to="/">Dataset Request Desk</Link>
        <div className="desk-bar-side">
          {user ? <span className="role-chip">{roleLabel[user.role]}</span> : null}
          <span className="user-name">{user?.name}</span>
          <button type="button" className="ghost" onClick={() => void onLogout()} disabled={pending}>
            {pending ? "Signing out" : "Sign out"}
          </button>
        </div>
      </header>
      {error ? (
        <p className="form-error desk-banner" role="alert">
          {error}
        </p>
      ) : null}
      <main className="desk-main">{children}</main>
    </div>
  );
}
