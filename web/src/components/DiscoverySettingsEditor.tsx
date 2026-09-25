import { useEffect, useState } from "react";
import { type DiscoverySettings, getDiscoverySettings, updateDiscoverySettings } from "../api";
import { useToken } from "../useToken";

export function DiscoverySettingsEditor({ workspaceId }: { workspaceId: number }) {
  const getToken = useToken();
  const [settings, setSettings] = useState<DiscoverySettings | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      const s = await getDiscoverySettings(await getToken(), workspaceId);
      if (active) setSettings(s);
    })();
    return () => {
      active = false;
    };
  }, [getToken, workspaceId]);

  if (!settings) return null;

  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded border border-gray-200 p-3"
      onSubmit={async (e) => {
        e.preventDefault();
        const form = new FormData(e.currentTarget);
        const updated = await updateDiscoverySettings(await getToken(), workspaceId, {
          monthly_call_budget: Number(form.get("budget")),
          scan_frequency: String(form.get("frequency")) as DiscoverySettings["scan_frequency"],
          tineye_enabled: form.get("tineye") === "on",
        });
        setSettings(updated);
      }}
    >
      <h3 className="w-full font-medium">Discovery settings</h3>
      <label className="text-sm">
        Monthly budget{" "}
        <input
          name="budget"
          type="number"
          defaultValue={settings.monthly_call_budget}
          className="w-24 border p-1"
        />
      </label>
      <label className="text-sm">
        Frequency{" "}
        <select name="frequency" defaultValue={settings.scan_frequency} className="border p-1">
          <option value="off">off</option>
          <option value="daily">daily</option>
          <option value="weekly">weekly</option>
        </select>
      </label>
      <label className="text-sm">
        <input name="tineye" type="checkbox" defaultChecked={settings.tineye_enabled} /> TinEye
      </label>
      <button className="rounded bg-gray-800 px-2 py-1 text-white">Save</button>
    </form>
  );
}
