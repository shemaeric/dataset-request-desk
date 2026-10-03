import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { failureMessage, listRequests } from "./api";
import { useAuth } from "./auth";
import { deskLead, deskMessage, deskStats, deskTitle } from "./dashboard";
import { Frame } from "./Frame";
import type { DeskRequest, Role } from "./types";
import { formatDeadline, statusLabel } from "./workflow";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: DeskRequest[] };

export function DeskHome() {
  const { state } = useAuth();
  if (state.status !== "ready") {
    return null;
  }
  return <Dashboard role={state.user.role} />;
}

function Dashboard({ role }: { role: Role }) {
  const [reloadKey, setReloadKey] = useState(0);
  const [load, setLoad] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    listRequests()
      .then((items) => {
        if (!cancelled) {
          setLoad({ status: "ready", items });
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

  const items = load.status === "ready" ? load.items : [];

  return (
    <Frame>
      <section className="hero">
        <h1>{deskTitle(role)}</h1>
        <p className="hero-lead">{deskLead(role)}</p>
        {load.status === "ready" ? <p className="hero-message">{deskMessage(role, items)}</p> : null}
      </section>
      {load.status === "loading" ? <p className="quiet">Loading your desk</p> : null}
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
        <div className="stat-row">
          {deskStats(role, items).map((stat) => (
            <div className="stat" key={stat.label}>
              <span>{stat.label}</span>
              <strong>{stat.value}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {load.status === "ready" && items.length > 0 ? (
        <div className="card-grid">
          {items.map((row) => (
            <RequestCard key={row.id} row={row} role={role} />
          ))}
        </div>
      ) : null}
    </Frame>
  );
}

function RequestCard({ row, role }: { row: DeskRequest; role: Role }) {
  const short =
    row.status === "in_progress" && row.assigned_episode_count < row.episodes_requested;
  return (
    <Link className="request-card" to={`/requests/${row.id}`}>
      <div className="request-card-top">
        <h2>{row.task_name}</h2>
        <span className={`pill ${row.status}`}>{statusLabel[row.status]}</span>
      </div>
      {role === "client" ? null : <p className="request-client">{row.client_name}</p>}
      <p className="facts">
        <span>
          {row.assigned_episode_count} / {row.episodes_requested} episodes
        </span>
        <span>Due {formatDeadline(row.deadline)}</span>
      </p>
      {short ? <p className="short">Needs more episodes</p> : null}
    </Link>
  );
}
