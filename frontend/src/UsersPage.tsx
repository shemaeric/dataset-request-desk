import { useEffect, useState, type FormEvent } from "react";
import { createUser, failureMessage, listUsers, updateUser } from "./api";
import { Frame } from "./Frame";
import type { Account, Role } from "./types";

const roles: Role[] = ["client", "operator", "admin"];

type FieldErrors = Partial<Record<"email" | "name" | "password", string>>;

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; accounts: Account[] };

function problems(email: string, name: string, password: string): FieldErrors {
  const errors: FieldErrors = {};
  const cleaned = email.trim();
  if (!cleaned || !cleaned.includes("@") || cleaned.startsWith("@") || cleaned.endsWith("@")) {
    errors.email = "Enter an email address.";
  }
  if (!name.trim()) {
    errors.name = "Enter a name.";
  }
  if (!password.trim()) {
    errors.password = "Enter a password.";
  }
  return errors;
}

export function UsersPage() {
  const [reloadKey, setReloadKey] = useState(0);
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("client");
  const [organisation, setOrganisation] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [cardError, setCardError] = useState<{ id: number; message: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    listUsers()
      .then((accounts) => {
        if (!cancelled) {
          setLoad({ status: "ready", accounts });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setLoad({ status: "error", message: failureMessage(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = problems(email, name, password);
    setFieldErrors(next);
    setFormError(null);
    setNotice(null);
    if (Object.keys(next).length > 0 || creating) {
      return;
    }
    setCreating(true);
    try {
      const created = await createUser({
        email: email.trim(),
        name: name.trim(),
        password,
        role,
        organisation: organisation.trim() ? organisation.trim() : null,
      });
      setEmail("");
      setName("");
      setPassword("");
      setRole("client");
      setOrganisation("");
      setNotice(`Added ${created.name}.`);
      setLoad({ status: "ready", accounts: await listUsers() });
    } catch (caught) {
      setFormError(failureMessage(caught));
    } finally {
      setCreating(false);
    }
  }

  async function onUpdate(account: Account, body: { role?: Role; is_active?: boolean }) {
    if (pendingId !== null) {
      return;
    }
    setCardError(null);
    setNotice(null);
    setPendingId(account.id);
    try {
      await updateUser(account.id, body);
      setLoad({ status: "ready", accounts: await listUsers() });
    } catch (caught) {
      setCardError({ id: account.id, message: failureMessage(caught) });
    } finally {
      setPendingId(null);
    }
  }

  const accounts = load.status === "ready" ? load.accounts : [];

  return (
    <Frame>
      <section className="hero">
        <h1>Users</h1>
        <p className="hero-lead">Accounts that can sign in to the desk.</p>
      </section>
      {load.status === "loading" ? <p className="quiet">Loading users</p> : null}
      {load.status === "error" ? (
        <div className="stack">
          <p className="form-error" role="alert">
            {load.message}
          </p>
          <button
            type="button"
            onClick={() => {
              setLoad({ status: "loading" });
              setReloadKey((value) => value + 1);
            }}
          >
            Try again
          </button>
        </div>
      ) : null}
      {load.status === "ready" ? (
        <form className="request-form" onSubmit={(event) => void onCreate(event)} noValidate>
          <h2>New user</h2>
          <div className="form-grid">
            <label>
              Email
              <input
                name="email"
                type="email"
                value={email}
                aria-invalid={Boolean(fieldErrors.email)}
                onChange={(event) => setEmail(event.target.value)}
              />
              {fieldErrors.email ? <span className="field-error">{fieldErrors.email}</span> : null}
            </label>
            <label>
              Name
              <input
                name="name"
                value={name}
                aria-invalid={Boolean(fieldErrors.name)}
                onChange={(event) => setName(event.target.value)}
              />
              {fieldErrors.name ? <span className="field-error">{fieldErrors.name}</span> : null}
            </label>
            <label>
              Role
              <select name="role" value={role} onChange={(event) => setRole(event.target.value as Role)}>
                {roles.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="form-grid">
            <label>
              Password
              <input
                name="password"
                type="password"
                value={password}
                aria-invalid={Boolean(fieldErrors.password)}
                onChange={(event) => setPassword(event.target.value)}
              />
              {fieldErrors.password ? (
                <span className="field-error">{fieldErrors.password}</span>
              ) : null}
            </label>
            <label>
              Organisation
              <input
                name="organisation"
                value={organisation}
                onChange={(event) => setOrganisation(event.target.value)}
              />
            </label>
          </div>
          {formError ? (
            <p className="form-error" role="alert">
              {formError}
            </p>
          ) : null}
          <button type="submit" disabled={creating}>
            {creating ? "Adding" : "Add user"}
          </button>
        </form>
      ) : null}
      {notice ? (
        <p className="form-success" role="status">
          {notice}
        </p>
      ) : null}
      {accounts.length > 0 ? (
        <div className="card-grid user-grid">
          {accounts.map((account) => (
            <article className="account-card" key={account.id}>
              <div className="request-card-top">
                <h2>{account.name}</h2>
                <span className={`pill ${account.is_active ? "accepted" : "rejected"}`}>
                  {account.is_active ? "Active" : "Inactive"}
                </span>
              </div>
              <p className="request-client">{account.email}</p>
              {account.organisation ? <p className="facts">{account.organisation}</p> : null}
              <div className="account-actions">
                <label>
                  Role
                  <select
                    value={account.role}
                    disabled={pendingId !== null}
                    onChange={(event) => {
                      const next = event.target.value as Role;
                      if (next !== account.role) {
                        void onUpdate(account, { role: next });
                      }
                    }}
                  >
                    {roles.map((item) => (
                      <option key={item} value={item}>
                        {item}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="ghost"
                  disabled={pendingId !== null}
                  onClick={() => void onUpdate(account, { is_active: !account.is_active })}
                >
                  {pendingId === account.id
                    ? "Saving"
                    : account.is_active
                      ? "Deactivate"
                      : "Activate"}
                </button>
              </div>
              {cardError?.id === account.id ? (
                <p className="form-error" role="alert">
                  {cardError.message}
                </p>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}
    </Frame>
  );
}
