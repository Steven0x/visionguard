const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface Me {
  id: number;
  email: string;
  role: "admin" | "reviewer";
  all_workspaces: boolean;
}

/** Fetch the current staff member, attaching the Clerk session token. */
export async function fetchMe(token: string): Promise<Me> {
  const res = await fetch(`${API_BASE_URL}/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`GET /me failed: ${res.status}`);
  }
  return (await res.json()) as Me;
}
