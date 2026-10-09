/** WebSocket subscription with auto-reconnect. Any server event invalidates the
 * relevant React Query caches, so screens update without manual refresh. */
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { tokenStore, wsUrl } from "@/services/api";

type Msg = { type: string; data: Record<string, unknown> };

const INVALIDATE: Record<string, string[][]> = {
  "table.status": [["board"], ["dashboard"], ["availability"], ["timeline"]],
  "availability.changed": [["availability"], ["timeline"], ["board"], ["bookings"]],
  "session.started": [["board"], ["dashboard"], ["sessions"]],
  "session.stopped": [["board"], ["dashboard"], ["sessions"], ["invoices"]],
  "session.paused": [["board"]],
  "session.resumed": [["board"]],
  "session.extended": [["board"]],
  "session.ready": [["board"]],
  "invoice.issued": [["dashboard"], ["invoices"]],
  "invoice.paid": [["dashboard"], ["invoices"]],
  "booking.created": [["bookings"], ["dashboard"]],
  "booking.confirmed": [["bookings"], ["dashboard"]],
  "order.updated": [["board"], ["order"]],
  "alert.created": [["alerts"], ["dashboard"]],
  "device.status": [["devices"], ["board"], ["dashboard"]],
  "detection.updated": [["detection"]],
  "approval.requested": [["approvals"]],
};

export function useRealtime(branchId: string | undefined, mode: "staff" | "public", onMessage?: (m: Msg) => void): boolean {
  const qc = useQueryClient();
  const [connected, setConnected] = useState(false);
  const cb = useRef(onMessage);
  cb.current = onMessage;

  useEffect(() => {
    if (!branchId) return;
    let ws: WebSocket | null = null;
    let stopped = false;
    let retry = 1000;
    let ping: ReturnType<typeof setInterval> | undefined;

    const connect = () => {
      const path = mode === "staff" ? `/ws/branches/${branchId}?token=${encodeURIComponent(tokenStore.get() ?? "")}` : `/ws/public/branches/${branchId}`;
      ws = new WebSocket(wsUrl(path));
      ws.onopen = () => {
        setConnected(true);
        retry = 1000;
        qc.invalidateQueries(); // catch up on anything missed while disconnected
        ping = setInterval(() => ws?.readyState === 1 && ws.send("ping"), 25000);
      };
      ws.onmessage = (ev) => {
        if (ev.data === "pong") return;
        try {
          const msg = JSON.parse(ev.data) as Msg;
          (INVALIDATE[msg.type] ?? [["board"]]).forEach((key) => qc.invalidateQueries({ queryKey: key }));
          cb.current?.(msg);
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (ping) clearInterval(ping);
        if (!stopped) setTimeout(connect, (retry = Math.min(retry * 2, 20000)));
      };
    };
    connect();
    return () => {
      stopped = true;
      if (ping) clearInterval(ping);
      ws?.close();
    };
  }, [branchId, mode, qc]);

  return connected;
}

/** Re-render every `ms` (live timers). */
export function useNow(ms = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}
