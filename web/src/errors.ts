/** Normalize any thrown value into a readable, user-facing sentence. The api.ts `request()`
 * client already throws Error objects whose message is the server's `detail` (or a formatted
 * 422), so for API failures this is just `.message` — never raw JSON or an "[object Object]". */
export function errorText(e: unknown): string {
  if (e instanceof Error && e.message) return e.message;
  if (typeof e === "string" && e) return e;
  return "Something went wrong. Please try again.";
}
