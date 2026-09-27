import { useAuth } from "@clerk/clerk-react";
import { useCallback } from "react";

/** Returns a getter for the current Clerk session token (throws if signed out).
 *
 * Memoized with useCallback so its identity is STABLE across renders. It's used in the
 * dependency arrays of effects/callbacks (App's fetchMe, each section's reload); returning a
 * fresh function every render retriggered those effects on every state update — the render loop
 * that fired ~21k GET /me. Clerk's getToken reference is stable, so this is too. */
export function useToken(): () => Promise<string> {
  const { getToken } = useAuth();
  return useCallback(async () => {
    const token = await getToken();
    if (!token) throw new Error("no session token");
    return token;
  }, [getToken]);
}
