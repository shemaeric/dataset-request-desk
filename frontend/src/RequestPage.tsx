import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  assignEpisode,
  failureMessage,
  getRequest,
  listEpisodes,
  removeEpisode,
  transitionRequest,
} from "./api";
import { useAuth } from "./auth";
import { Frame } from "./Frame";
import type { Episode, EpisodePage, EpisodeQuality, RequestDetail } from "./types";
import { clientRequestMessage } from "./dashboard";
import { formatDeadline, staffTransition, statusLabel } from "./workflow";

const PAGE_SIZE = 20;

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; request: RequestDetail };

export function RequestPage() {
  const { state } = useAuth();
  const params = useParams();
  const requestId = Number(params.requestId);
  const role = state.status === "ready" ? state.user.role : null;
  const [reloadKey, setReloadKey] = useState(0);
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [actionError, setActionError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (role === null) {
      return;
    }
    if (!Number.isInteger(requestId) || requestId < 1) {
      setLoad({ status: "error", message: "Request not found" });
      return;
    }
    let cancelled = false;
    getRequest(requestId)
      .then((request) => {
        if (!cancelled) {
          setLoad({ status: "ready", request });
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
  }, [requestId, reloadKey, role]);

  if (state.status !== "ready") {
    return null;
  }
  if (state.user.role === "client") {
    return (
      <ClientRequest
        load={load}
        onRetry={() => {
          setLoad({ status: "loading" });
          setReloadKey((value) => value + 1);
        }}
      />
    );
  }

  const request = load.status === "ready" ? load.request : null;
  const move = request ? staffTransition(request.status) : null;
  const short =
    request !== null &&
    request.status === "in_progress" &&
    request.assigned_episode_count < request.episodes_requested;

  async function onTransition() {
    if (!request || !move) {
      return;
    }
    setActionError(null);
    setPending(true);
    try {
      const next = await transitionRequest(request.id, move.status);
      setLoad({ status: "ready", request: next });
    } catch (error) {
      setActionError(failureMessage(error));
    } finally {
      setPending(false);
    }
  }

  return (
    <Frame>
      <Link className="back" to="/">
        All requests
      </Link>
      {load.status === "loading" ? <p className="quiet">Loading request</p> : null}
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
      {request ? (
        <>
          <div className="summary">
            <div>
              <h1>{request.task_name}</h1>
              <p className="meta">
                <span className={`pill ${request.status}`}>{statusLabel[request.status]}</span>
                <span>{request.client_name}</span>
                <span>Due {formatDeadline(request.deadline)}</span>
                <span>
                  <strong>
                    {request.assigned_episode_count} / {request.episodes_requested}
                  </strong>{" "}
                  episodes
                </span>
              </p>
            </div>
            {move ? (
              <button type="button" onClick={() => void onTransition()} disabled={pending}>
                {pending ? "Saving" : move.label}
              </button>
            ) : null}
          </div>
          {request.notes ? <p className="notes">{request.notes}</p> : null}
          {short ? (
            <p className="notice">
              Needs {request.episodes_requested - request.assigned_episode_count} more{" "}
              {request.episodes_requested - request.assigned_episode_count === 1
                ? "episode"
                : "episodes"}{" "}
              before delivery.
            </p>
          ) : null}
          {actionError ? (
            <p className="form-error" role="alert">
              {actionError}
            </p>
          ) : null}
          {request.status !== "in_progress" ? (
            <p className="quiet">Episodes can only be changed while the request is in progress.</p>
          ) : null}
          <div className="work">
            <AssignedList
              request={request}
              onChange={(next) => {
                setActionError(null);
                setLoad({ status: "ready", request: next });
              }}
            />
            <EpisodeFinder
              request={request}
              onChange={(next) => {
                setActionError(null);
                setLoad({ status: "ready", request: next });
              }}
            />
          </div>
        </>
      ) : null}
    </Frame>
  );
}

function ClientRequest({ load, onRetry }: { load: LoadState; onRetry: () => void }) {
  const request = load.status === "ready" ? load.request : null;
  return (
    <Frame>
      <Link className="back" to="/">
        Your requests
      </Link>
      {load.status === "loading" ? <p className="quiet">Loading request</p> : null}
      {load.status === "error" ? (
        <div className="stack">
          <p className="form-error" role="alert">
            {load.message}
          </p>
          <button type="button" onClick={onRetry}>
            Try again
          </button>
        </div>
      ) : null}
      {request ? (
        <article className="client-detail">
          <div className="request-card-top">
            <h1>{request.task_name}</h1>
            <span className={`pill ${request.status}`}>{statusLabel[request.status]}</span>
          </div>
          <p className="hero-message">{clientRequestMessage(request)}</p>
          <p className="facts">
            <span>
              {request.assigned_episode_count} / {request.episodes_requested} episodes
            </span>
            <span>Due {formatDeadline(request.deadline)}</span>
          </p>
          {request.notes ? <p className="notes">{request.notes}</p> : null}
        </article>
      ) : null}
      {request && request.assignments.length > 0 ? (
        <section className="panel client-episodes">
          <h2>Episodes</h2>
          <ul className="episode-list">
            {request.assignments.map((episode) => (
              <li className="episode-card" key={episode.episode_id}>
                <div>
                  <strong>{episode.source_episode_id}</strong>
                  <span className="quiet">
                    {episode.task_name} · <Quality value={episode.quality} />
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </Frame>
  );
}

function AssignedList({
  request,
  onChange,
}: {
  request: RequestDetail;
  onChange: (next: RequestDetail) => void;
}) {
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const open = request.status === "in_progress";

  async function onRemove(episodeId: number) {
    setError(null);
    setPendingId(episodeId);
    try {
      await removeEpisode(request.id, episodeId);
      onChange(await getRequest(request.id));
    } catch (caught) {
      setError(failureMessage(caught));
    } finally {
      setPendingId(null);
    }
  }

  return (
    <section className="panel">
      <h2>Assigned</h2>
      {request.assignments.length === 0 ? <p className="quiet">None yet.</p> : null}
      <ul className="episode-list">
        {request.assignments.map((episode) => (
          <li className="episode-card" key={episode.episode_id}>
            <div>
              <strong>{episode.source_episode_id}</strong>
              <span className="quiet">
                {episode.task_name} · <Quality value={episode.quality} />
              </span>
            </div>
            {open ? (
              <button
                type="button"
                className="ghost"
                disabled={pendingId !== null}
                onClick={() => void onRemove(episode.episode_id)}
              >
                {pendingId === episode.episode_id ? "Removing" : "Remove"}
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );
}

function EpisodeFinder({
  request,
  onChange,
}: {
  request: RequestDetail;
  onChange: (next: RequestDetail) => void;
}) {
  const [taskName, setTaskName] = useState("");
  const [quality, setQuality] = useState<EpisodeQuality | "">("");
  const [applied, setApplied] = useState({ taskName: "", quality: "" as EpisodeQuality | "" });
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<EpisodePage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{ id: number; message: string } | null>(null);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const open = request.status === "in_progress";
  const assignedHere = new Set(request.assignments.map((episode) => episode.episode_id));

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listEpisodes({ taskName: applied.taskName, quality: applied.quality, limit: PAGE_SIZE, offset })
      .then((next) => {
        if (!cancelled) {
          setPage(next);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(failureMessage(caught));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [applied, offset]);

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setOffset(0);
    setApplied({ taskName, quality });
  }

  async function onAssign(episodeId: number) {
    setRowError(null);
    setPendingId(episodeId);
    try {
      await assignEpisode(request.id, episodeId);
      onChange(await getRequest(request.id));
    } catch (caught) {
      setRowError({ id: episodeId, message: failureMessage(caught) });
    } finally {
      setPendingId(null);
    }
  }

  const from = page && page.total > 0 ? page.offset + 1 : 0;
  const to = page ? page.offset + page.items.length : 0;

  return (
    <section className="panel">
      <h2>Find episodes</h2>
      <form className="filters" onSubmit={onSearch}>
        <label>
          Task
          <input value={taskName} onChange={(event) => setTaskName(event.target.value)} />
        </label>
        <label>
          Quality
          <select
            value={quality}
            onChange={(event) => setQuality(event.target.value as EpisodeQuality | "")}
          >
            <option value="">Any</option>
            <option value="good">Good</option>
            <option value="usable">Usable</option>
            <option value="bad">Bad</option>
          </select>
        </label>
        <button type="submit" disabled={loading}>
          {loading ? "Searching" : "Search"}
        </button>
      </form>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      {loading && !page ? <p className="quiet">Loading episodes</p> : null}
      {page && page.items.length === 0 ? <p className="quiet">No episodes match.</p> : null}
      <ul className="episode-list">
        {page?.items.map((episode) => (
          <EpisodeRow
            key={episode.id}
            episode={episode}
            open={open}
            assigned={assignedHere.has(episode.id)}
            pending={pendingId !== null}
            busy={pendingId === episode.id}
            error={rowError?.id === episode.id ? rowError.message : null}
            onAssign={() => void onAssign(episode.id)}
          />
        ))}
      </ul>
      {page && page.total > page.limit ? (
        <div className="pager">
          <span>
            {from}–{to} of {page.total}
          </span>
          <button type="button" disabled={loading || offset === 0} onClick={() => setOffset(offset - PAGE_SIZE)}>
            Previous
          </button>
          <button
            type="button"
            disabled={loading || offset + PAGE_SIZE >= page.total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      ) : null}
    </section>
  );
}

function EpisodeRow({
  episode,
  open,
  assigned,
  pending,
  busy,
  error,
  onAssign,
}: {
  episode: Episode;
  open: boolean;
  assigned: boolean;
  pending: boolean;
  busy: boolean;
  error: string | null;
  onAssign: () => void;
}) {
  const ineligible = episode.quality === "bad";
  return (
    <li className="episode-card">
      <div>
        <strong>{episode.source_episode_id}</strong>
        <span className="quiet">
          {episode.task_name} · {episode.robot_id} · <Quality value={episode.quality} />
        </span>
        {open && ineligible ? (
          <span className="quiet">Episode quality must be good or usable</span>
        ) : null}
        {error ? (
          <span className="form-error" role="alert">
            {error}
          </span>
        ) : null}
      </div>
      {open && !assigned && !ineligible ? (
        <button type="button" disabled={pending} onClick={onAssign}>
          {busy ? "Assigning" : "Assign"}
        </button>
      ) : null}
      {assigned ? <span className="quiet">Assigned here</span> : null}
    </li>
  );
}

function Quality({ value }: { value: EpisodeQuality }) {
  return <span className={`quality ${value}`}>{value}</span>;
}
