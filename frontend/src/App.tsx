import { useEffect, useState } from "react";
import { getHealth } from "./api";

type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; status: string }
  | { kind: "error"; message: string };

export function App() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then((body) => {
        if (!cancelled) {
          setHealth({ kind: "ok", status: body.status });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : "Health check failed";
          setHealth({ kind: "error", message });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="shell">
      <p className="eyebrow">Internal platform</p>
      <h1>Dataset Request Desk</h1>
      <p className="lede">
        Clients request robot teleoperation datasets. Operators fulfil those requests from recorded
        episodes.
      </p>
      <p className="health" role="status">
        {health.kind === "loading" && "Checking API…"}
        {health.kind === "ok" && `API health: ${health.status}`}
        {health.kind === "error" && health.message}
      </p>
    </main>
  );
}
