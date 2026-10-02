import { useAuth } from "@clerk/clerk-react";
import { useCallback } from "react";

/** Dev-only capture mode (Slice 14 screenshots). When VITE_DEV_AUTH=1 the app skips Clerk and
 * uses a pre-minted AUTH_TEST_MODE token injected into localStorage by the Playwright capture
 * script. The flag is unset in every real build, so this branch is dead in prod. See
 * scripts/design_capture.py. */
const DEV_AUTH = import.meta.env.VITE_DEV_AUTH === "1";

/** Returns a getter for the current Clerk session token (throws if signed out).
 *
 * Memoized with useCallback so its identity is STABLE across renders. It's used in the
 * dependency arrays of effects/callbacks (App's fetchMe, each section's reload); returning a
 * fresh function every render retriggered those effects on every state update — the render loop
 * that fired ~21k GET /me. Clerk's getToken reference is stable, so this is too. */
export function useToken(): () => Promise<string> {
  const { getToken } = useAuth();
  return useCallback(async () => {
    if (DEV_AUTH) {
      const token = localStorage.getItem("vg_dev_token");
      if (!token) throw new Error("no dev token (VITE_DEV_AUTH capture mode)");
      return token;
    }
    const token = await getToken();
    if (!token) throw new Error("no session token");
    return token;
  }, [getToken]);
}
