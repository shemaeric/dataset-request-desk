export type Role = "client" | "operator" | "admin";

export type User = {
  id: number;
  email: string;
  name: string;
  role: Role;
  organisation: string | null;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}
