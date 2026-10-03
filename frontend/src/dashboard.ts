import type { DeskRequest, RequestStatus, Role } from "./types";

function count(items: DeskRequest[], status: RequestStatus): number {
  return items.filter((item) => item.status === status).length;
}

function phrase(amount: number, singular: string, plural = `${singular}s`): string {
  return `${amount} ${amount === 1 ? singular : plural}`;
}

export function deskTitle(role: Role): string {
  if (role === "client") {
    return "Your requests";
  }
  if (role === "admin") {
    return "All requests";
  }
  return "Queue";
}

export function deskLead(role: Role): string {
  if (role === "client") {
    return "Requests submitted on your account.";
  }
  if (role === "admin") {
    return "Every request on the desk, including ones operators are filling.";
  }
  return "Requests you can start, fill, and deliver.";
}

export function deskMessage(role: Role, items: DeskRequest[]): string {
  if (items.length === 0) {
    if (role === "client") {
      return "You have no requests yet. Submit one to put it on the desk.";
    }
    if (role === "admin") {
      return "No client has submitted a request yet.";
    }
    return "The queue is empty. New client requests will land here.";
  }

  const delivered = count(items, "delivered");
  const inProgress = count(items, "in_progress");
  const submitted = count(items, "submitted");
  const rejected = count(items, "rejected");
  const short = items.filter(
    (item) =>
      item.status === "in_progress" && item.assigned_episode_count < item.episodes_requested,
  ).length;

  if (role === "client") {
    if (delivered > 0) {
      return `${phrase(delivered, "delivery is", "deliveries are")} ready for your review.`;
    }
    if (rejected > 0) {
      return `${phrase(rejected, "request was", "requests were")} sent back and can be reworked.`;
    }
    if (inProgress > 0) {
      return `An operator is working on ${phrase(inProgress, "request")}.`;
    }
    if (submitted > 0) {
      return "Your requests are waiting for an operator to start.";
    }
    return "Everything here has been accepted.";
  }

  if (short > 0) {
    return `${phrase(short, "request")} still ${short === 1 ? "needs" : "need"} episodes before delivery.`;
  }
  if (submitted > 0) {
    return `${phrase(submitted, "new request is", "new requests are")} waiting to be started.`;
  }
  if (rejected > 0) {
    return `${phrase(rejected, "rejected request")} can be picked up again.`;
  }
  if (inProgress > 0) {
    return role === "admin"
      ? `Operators are filling ${phrase(inProgress, "request")}.`
      : `You have ${phrase(inProgress, "request")} in progress.`;
  }
  if (role === "admin") {
    return "Nothing is waiting on staff. Accepted and delivered requests stay visible.";
  }
  return "Nothing needs a staff step right now.";
}

export function clientRequestMessage(request: DeskRequest): string {
  const left = request.episodes_requested - request.assigned_episode_count;
  if (request.status === "submitted") {
    return "This is with the desk. An operator has not started it yet.";
  }
  if (request.status === "in_progress" && left > 0) {
    const noun = left === 1 ? "episode is" : "episodes are";
    return `An operator is assigning episodes. ${left} more ${noun} still needed.`;
  }
  if (request.status === "in_progress") {
    return "Enough episodes are assigned. An operator can deliver this.";
  }
  if (request.status === "delivered") {
    return "This delivery is ready for your review.";
  }
  if (request.status === "rejected") {
    return "This was sent back. An operator can start the rework.";
  }
  return "You accepted this delivery.";
}

export type DeskStat = { label: string; value: number };

export function deskStats(role: Role, items: DeskRequest[]): DeskStat[] {
  if (role === "client") {
    return [
      { label: "Waiting", value: count(items, "submitted") },
      { label: "In progress", value: count(items, "in_progress") },
      { label: "To review", value: count(items, "delivered") },
      { label: "Accepted", value: count(items, "accepted") },
    ];
  }
  const short = items.filter(
    (item) => item.status === "in_progress" && item.assigned_episode_count < item.episodes_requested,
  ).length;
  return [
    { label: "To start", value: count(items, "submitted") },
    { label: "In progress", value: count(items, "in_progress") },
    { label: "Short", value: short },
    { label: "Delivered", value: count(items, "delivered") },
  ];
}
