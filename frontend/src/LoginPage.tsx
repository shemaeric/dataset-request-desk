import { type FormEvent, useState } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "./auth";
import { ApiError } from "./types";

export function LoginPage() {
  const { state, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (state.status === "loading") {
    return (
      <div className="login">
        <p className="login-status">Checking session</p>
      </div>
    );
  }
  if (state.status === "ready") {
    return <Navigate to="/" replace />;
  }

  const sessionError = state.status === "error" ? state.message : null;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      await login(email, password);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not reach the API");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="login">
      <aside className="login-aside">
        <p className="login-mark">Dataset Request Desk</p>
        <div>
          <h1>Sign in to the desk.</h1>
          <p>Use the account issued for your role.</p>
        </div>
      </aside>
      <main className="login-panel">
        <form className="login-card" onSubmit={(event) => void onSubmit(event)}>
          <h2>Sign in</h2>
          <label>
            Email
            <input
              type="email"
              name="email"
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
          </label>
          <label>
            Password
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error || sessionError ? (
            <p className="form-error" role="alert">
              {error ?? sessionError}
            </p>
          ) : null}
          <button type="submit" disabled={pending}>
            {pending ? "Signing in" : "Sign in"}
          </button>
        </form>
      </main>
    </div>
  );
}
