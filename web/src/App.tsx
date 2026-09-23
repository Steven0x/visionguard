import {
  SignedIn,
  SignedOut,
  SignInButton,
  UserButton,
} from "@clerk/clerk-react";
import { useEffect, useState } from "react";
import { fetchMe, type Me } from "./api";
import { WorkspaceDetail } from "./components/WorkspaceDetail";
import { WorkspaceList } from "./components/WorkspaceList";
import { useToken } from "./useToken";

function Console() {
  const getToken = useToken();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openWorkspace, setOpenWorkspace] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const result = await fetchMe(await getToken());
        if (active) setMe(result);
      } catch (e) {
        if (active) setError(String(e));
      }
    })();
    return () => {
      active = false;
    };
  }, [getToken]);

  if (error) return <p className="text-red-600">{error}</p>;
  if (!me) return <p className="text-gray-500">Loading…</p>;

  const isAdmin = me.role === "admin";
  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-500">
        Signed in as {me.email} ({me.role})
      </p>
      {openWorkspace === null ? (
        <WorkspaceList isAdmin={isAdmin} onOpen={setOpenWorkspace} />
      ) : (
        <WorkspaceDetail
          workspaceId={openWorkspace}
          isAdmin={isAdmin}
          onBack={() => setOpenWorkspace(null)}
        />
      )}
    </div>
  );
}

export default function App() {
  return (
    <main className="mx-auto max-w-3xl space-y-4 p-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">VisionGuard</h1>
        <SignedIn>
          <UserButton />
        </SignedIn>
      </div>
      <SignedOut>
        <SignInButton mode="modal" />
      </SignedOut>
      <SignedIn>
        <Console />
      </SignedIn>
    </main>
  );
}
