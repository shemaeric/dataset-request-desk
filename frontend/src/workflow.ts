import type { RequestStatus } from "./types";

export const statusLabel: Record<RequestStatus, string> = {
  submitted: "Submitted",
  in_progress: "In progress",
  delivered: "Delivered",
  accepted: "Accepted",
  rejected: "Rejected",
};

const staffMove: Partial<Record<RequestStatus, { status: RequestStatus; label: string }>> = {
  submitted: { status: "in_progress", label: "Start work" },
  in_progress: { status: "delivered", label: "Mark delivered" },
  rejected: { status: "in_progress", label: "Start rework" },
};

export function staffTransition(
  status: RequestStatus,
): { status: RequestStatus; label: string } | null {
  return staffMove[status] ?? null;
}

export function formatWhen(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function formatDeadline(value: string): string {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) {
    return value;
  }
  return new Intl.DateTimeFormat("en", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(Date.UTC(year, month - 1, day)));
}
