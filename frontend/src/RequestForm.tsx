import { useRef, useState, type FormEvent } from "react";
import { createRequest, failureMessage } from "./api";
import type { DeskRequest } from "./types";

const TASK_NAME_MAX = 200;
const NOTES_MAX = 2_000;
const EPISODES_MAX = 100_000;
const DEADLINE_DAYS = 365 * 5;

type FieldName = "task_name" | "episodes_requested" | "deadline" | "notes";
type FieldErrors = Partial<Record<FieldName, string>>;

function utcDay(offset: number): string {
  const now = new Date();
  const day = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + offset));
  return day.toISOString().slice(0, 10);
}

function problems(values: {
  taskName: string;
  episodes: string;
  deadline: string;
  notes: string;
}): FieldErrors {
  const errors: FieldErrors = {};
  const taskName = values.taskName.trim();
  if (!taskName) {
    errors.task_name = "Enter a task name.";
  } else if (taskName.length > TASK_NAME_MAX) {
    errors.task_name = `Task name can be at most ${TASK_NAME_MAX} characters.`;
  }

  if (!/^\d+$/.test(values.episodes.trim())) {
    errors.episodes_requested = `Enter a whole number from 1 to ${EPISODES_MAX}.`;
  } else {
    const count = Number(values.episodes);
    if (count < 1 || count > EPISODES_MAX) {
      errors.episodes_requested = `Enter a whole number from 1 to ${EPISODES_MAX}.`;
    }
  }

  const earliest = utcDay(0);
  const latest = utcDay(DEADLINE_DAYS);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(values.deadline)) {
    errors.deadline = "Choose a deadline.";
  } else if (values.deadline < earliest || values.deadline > latest) {
    errors.deadline = "Deadline must be from today through five years ahead.";
  }

  if (values.notes.trim().length > NOTES_MAX) {
    errors.notes = `Notes can be at most ${NOTES_MAX} characters.`;
  }
  return errors;
}

export function RequestForm({
  onCreated,
  onCancel,
}: {
  onCreated: (row: DeskRequest) => void;
  onCancel?: () => void;
}) {
  const [taskName, setTaskName] = useState("");
  const [episodes, setEpisodes] = useState("1");
  const [deadline, setDeadline] = useState("");
  const [notes, setNotes] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const busy = useRef(false);
  const earliest = utcDay(0);
  const latest = utcDay(DEADLINE_DAYS);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = problems({ taskName, episodes, deadline, notes });
    setErrors(next);
    setError(null);
    if (Object.keys(next).length > 0 || busy.current) {
      return;
    }
    busy.current = true;
    setPending(true);
    try {
      const created = await createRequest({
        task_name: taskName.trim(),
        episodes_requested: Number(episodes),
        deadline,
        notes: notes.trim() ? notes.trim() : null,
      });
      setTaskName("");
      setEpisodes("1");
      setDeadline("");
      setNotes("");
      onCreated(created);
    } catch (caught) {
      setError(failureMessage(caught));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  return (
    <form className="request-form" onSubmit={(event) => void onSubmit(event)} noValidate>
      <div className="request-card-top">
        <h2>New request</h2>
        {onCancel ? (
          <button type="button" className="ghost" onClick={onCancel} disabled={pending}>
            Cancel
          </button>
        ) : null}
      </div>
      <div className="form-grid">
        <label>
          Task name
          <input
            name="task_name"
            value={taskName}
            maxLength={TASK_NAME_MAX}
            aria-invalid={Boolean(errors.task_name)}
            onChange={(event) => setTaskName(event.target.value)}
          />
          {errors.task_name ? <span className="field-error">{errors.task_name}</span> : null}
        </label>
        <label>
          Episodes
          <input
            name="episodes_requested"
            inputMode="numeric"
            value={episodes}
            aria-invalid={Boolean(errors.episodes_requested)}
            onChange={(event) => setEpisodes(event.target.value)}
          />
          {errors.episodes_requested ? (
            <span className="field-error">{errors.episodes_requested}</span>
          ) : null}
        </label>
        <label>
          Deadline
          <input
            name="deadline"
            type="date"
            value={deadline}
            min={earliest}
            max={latest}
            aria-invalid={Boolean(errors.deadline)}
            onChange={(event) => setDeadline(event.target.value)}
          />
          {errors.deadline ? <span className="field-error">{errors.deadline}</span> : null}
        </label>
      </div>
      <label>
        Notes
        <textarea
          name="notes"
          rows={3}
          value={notes}
          maxLength={NOTES_MAX}
          aria-invalid={Boolean(errors.notes)}
          onChange={(event) => setNotes(event.target.value)}
        />
        {errors.notes ? <span className="field-error">{errors.notes}</span> : null}
      </label>
      {error ? (
        <p className="form-error" role="alert">
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={pending}>
        {pending ? "Submitting" : "Submit request"}
      </button>
    </form>
  );
}
