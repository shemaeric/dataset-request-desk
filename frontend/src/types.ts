export type Role = "client" | "operator" | "admin";

export type User = {
  id: number;
  email: string;
  name: string;
  role: Role;
  organisation: string | null;
};

export type Account = User & {
  is_active: boolean;
};

export type RequestStatus =
  | "submitted"
  | "in_progress"
  | "delivered"
  | "accepted"
  | "rejected";

export type EpisodeQuality = "good" | "usable" | "bad";

export type DeskRequest = {
  id: number;
  client_id: number;
  client_name: string;
  task_name: string;
  episodes_requested: number;
  assigned_episode_count: number;
  deadline: string;
  notes: string | null;
  status: RequestStatus;
  created_at: string;
  updated_at: string;
};

export type AssignedEpisode = {
  episode_id: number;
  source_episode_id: string;
  task_name: string;
  quality: EpisodeQuality;
};

export type StatusChange = {
  from_status: RequestStatus | null;
  to_status: RequestStatus;
  actor_user_id: number;
  changed_at: string;
};

export type RequestDetail = DeskRequest & {
  assignments: AssignedEpisode[];
  status_history: StatusChange[];
};

export type Episode = {
  id: number;
  source_episode_id: string;
  robot_id: string;
  task_name: string;
  recorded_at: string;
  duration_seconds: number;
  operator_name: string;
  quality: EpisodeQuality;
};

export type EpisodePage = {
  items: Episode[];
  total: number;
  limit: number;
  offset: number;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}
