import { useAuth } from "@clerk/clerk-react";

/** Returns a getter for the current Clerk session token (throws if signed out). */
export function useToken(): () => Promise<string> {
  const { getToken } = useAuth();
  return async () => {
    const token = await getToken();
    if (!token) throw new Error("no session token");
    return token;
  };
}
