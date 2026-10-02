import {
  SignedIn,
  SignedOut,
  SignInButton,
  UserButton,
} from "@clerk/clerk-react";
import { useCallback, useEffect, useState } from "react";
import { fetchMe, listWorkspaces, type Me, type Workspace } from "./api";
import { AppShell, type NavItem } from "./components/AppShell";
import { AgencyPortal } from "./components/portal/AgencyPortal";
import { ThemeToggle } from "./components/ThemeToggle";
import { Button, EmptyState, Select, SkeletonRows } from "./components/ui";
import { WorkspaceDetail, type Section } from "./components/WorkspaceDetail";
import { WorkspaceList } from "./components/WorkspaceList";
import { errorText } from "./errors";
import { useToken } from "./useToken";

// Dev-only capture mode (Slice 14 screenshots): skip Clerk's sign-in gate. VITE_DEV_AUTH is
// unset in every real build, so this is dead there. See useToken.ts + scripts/design_capture.py.
const DEV_AUTH = import.meta.env.VITE_DEV_AUTH === "1";

function sectionNav(isAdmin: boolean): NavItem[] {
  const base: NavItem[] = [
    { key: "inbox", label: "Review inbox" },
    { key: "cases", label: "Cases" },
    { key: "followups", label: "Follow-ups" },
    { key: "reports", label: "Reports" },
    { key: "subjects", label: "Subjects" },
  ];
  return isAdmin ? [...base, { key: "settings", label: "Settings" }] : base;
}

function StaffConsole({ me }: { me: Me }) {
  const getToken = useToken();
  const isAdmin = me.role === "admin";
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openWorkspace, setOpenWorkspace] = useState<number | null>(null);
  const [section, setSection] = useState<Section>("inbox");

  const reload = useCallback(async () => {
    try {
      setWorkspaces(await listWorkspaces(await getToken()));
    } catch (e) {
      setError(errorText(e));
    }
  }, [getToken]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const open = openWorkspace !== null;
  const nav = open ? sectionNav(isAdmin) : [{ key: "workspaces", label: "Workspaces" }];
  const activeNav = open ? section : "workspaces";

  const switcher = (
    <Select
      aria-label="Workspace"
      value={openWorkspace ?? ""}
      onChange={(e) => {
        const v = e.target.value;
        setOpenWorkspace(v ? Number(v) : null);
        setSection("inbox");
      }}
    >
      <option value="">All workspaces</option>
      {(workspaces ?? []).map((w) => (
        <option key={w.id} value={w.id}>
          {w.name}
        </option>
      ))}
    </Select>
  );

  const topRight = (
    <>
      <span className="hidden text-xs text-fg-muted sm:inline">{me.email}</span>
      <ThemeToggle />
      {!DEV_AUTH && <UserButton />}
    </>
  );

  return (
    <AppShell
      nav={nav}
      activeNav={activeNav}
      onNav={(k) => open && setSection(k as Section)}
      switcher={switcher}
      topRight={topRight}
    >
      {workspaces === null ? (
        <SkeletonRows rows={5} />
      ) : error ? (
        <EmptyState
          title="Couldn’t load workspaces"
          description={error}
          action={<Button onClick={() => void reload()}>Retry</Button>}
        />
      ) : openWorkspace === null ? (
        <WorkspaceList
          workspaces={workspaces}
          isAdmin={isAdmin}
          onOpen={(id) => {
            setOpenWorkspace(id);
            setSection("inbox");
          }}
          onReload={reload}
        />
      ) : (
        <WorkspaceDetail
          workspaceId={openWorkspace}
          section={section}
          isAdmin={isAdmin}
          keepBlurDefault={me.review_keep_blur}
        />
      )}
    </AppShell>
  );
}

function Console() {
  const getToken = useToken();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const result = await fetchMe(await getToken());
        if (active) setMe(result);
      } catch (e) {
        if (active) setError(errorText(e));
      }
    })();
    return () => {
      active = false;
    };
  }, [getToken]);

  if (error) {
    return (
      <div className="mx-auto max-w-md p-8">
        <EmptyState title="Couldn’t sign you in" description={error} />
      </div>
    );
  }
  if (!me) {
    return (
      <div className="mx-auto max-w-md p-8">
        <SkeletonRows rows={4} />
      </div>
    );
  }

  // Agency users get the customer portal and NONE of the staff console components.
  if (me.role === "agency") return <AgencyPortal />;
  return <StaffConsole me={me} />;
}

function SignInScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg p-6">
      <div className="w-full max-w-sm space-y-6 rounded-xl bg-surface p-8 text-center shadow-card ring-1 ring-line">
        <div className="flex items-center justify-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-base font-bold text-primary-fg">
            V
          </span>
          <span className="text-lg font-bold tracking-tight">VisionGuard</span>
        </div>
        <p className="text-sm text-fg-muted">Sign in to the enforcement console.</p>
        <SignInButton mode="modal">
          <Button className="w-full">Sign in</Button>
        </SignInButton>
      </div>
    </div>
  );
}

export default function App() {
  if (DEV_AUTH) return <Console />;
  return (
    <>
      <SignedOut>
        <SignInScreen />
      </SignedOut>
      <SignedIn>
        <Console />
      </SignedIn>
    </>
  );
}
