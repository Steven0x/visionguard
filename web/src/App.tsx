import {
  SignedIn,
  SignedOut,
  SignInButton,
  UserButton,
  useAuth,
} from "@clerk/clerk-react";
import { useEffect, useState } from "react";
import { fetchMe, type Me } from "./api";

function Dashboard() {
  const { getToken } = useAuth();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const token = await getToken();
        if (!token) throw new Error("no session token");
        const result = await fetchMe(token);
        if (active) setMe(result);
      } catch (err) {
        if (active) setError(String(err));
      }
    })();
    return () => {
      active = false;
    };
  }, [getToken]);

  if (error) return <p className="text-red-600">{error}</p>;
  if (!me) return <p className="text-gray-500">Loading…</p>;

  return (
    <div className="rounded border border-gray-200 p-4">
      <p className="font-medium">{me.email}</p>
      <p className="text-sm text-gray-600">
        role: {me.role}
        {me.all_workspaces ? " · all workspaces" : ""}
      </p>
    </div>
  );
}

export default function App() {
  return (
    <main className="mx-auto max-w-xl space-y-4 p-8">
      <h1 className="text-2xl font-semibold">VisionGuard</h1>
      <SignedOut>
        <SignInButton mode="modal" />
      </SignedOut>
      <SignedIn>
        <UserButton />
        <Dashboard />
      </SignedIn>
    </main>
  );
}
