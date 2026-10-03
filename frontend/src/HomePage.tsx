import { useState } from "react";
import { useAuth } from "./auth";
import { ApiError, type Role } from "./types";

const roleLabel: Record<Role, string> = {
  client: "Client",
  operator: "Operator",
  admin: "Admin",
};

export function HomePage() {
  const { state, logout } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (state.status !== "ready") {
    return null;
  }
  const { user } = state;
  const organisation =
    user.organisation && user.organisation !== user.name ? user.organisation : null;

  async function onLogout() {
    setError(null);
    setPending(true);
    try {
      await logout();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not reach the API");
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <header className="top">
        <span>Dataset Request Desk</span>
        <button type="button" onClick={() => void onLogout()} disabled={pending}>
          {pending ? "Signing out" : "Sign out"}
        </button>
      </header>
      <main className="shell">
        <h1>{user.name}</h1>
        <p className="lede">
          {roleLabel[user.role]}
          {organisation ? ` · ${organisation}` : ""}
        </p>
        <p className="quiet">{user.email}</p>
        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : null}
      </main>
    </>
  );
}
