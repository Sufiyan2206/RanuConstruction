/** Live table grid + per-table action sheet (start / pause / extend / add items / stop & bill). */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post, ApiError } from "@/services/api";
import type { BoardRow, Invoice, Order, ProductStock, Session } from "@/types/api";
import { Badge, Button, ErrorBox, Field, Input, Modal, Select, useToast } from "@/components/ui";
import { TABLE_BORDER, TableStatusBadge } from "@/components/status";
import { CustomerPicker, type PickedCustomer } from "@/components/CustomerPicker";
import { InvoicePanel } from "@/components/InvoicePanel";
import { useNow } from "@/hooks/useRealtime";
import { cn } from "@/lib/cn";
import { duration, money, time } from "@/lib/format";
import { useAuth } from "@/stores/auth";
import { TableArt, tableImage } from "@/components/TableArt";

function elapsed(s: Session, now: number): number {
  if (!s.started_at) return 0;
  const ref = s.paused_at ? new Date(s.paused_at).getTime() : now;
  return Math.floor((ref - new Date(s.started_at).getTime()) / 1000) - (s.total_paused_seconds || 0);
}

export function TableCard({ row, onOpen }: { row: BoardRow; onOpen: () => void }) {
  const now = useNow(1000);
  const s = row.session;
  const running = s && (s.status === "ACTIVE" || s.status === "PAUSED");
  const endingSoon = s?.planned_end_at && new Date(s.planned_end_at).getTime() - now < 10 * 60000;
  const offline = row.devices.some((d) => d.status !== "ONLINE");
  return (
    <button onClick={onOpen} aria-label={`Table ${row.table.table_number}`}
      className={cn("group flex min-h-36 flex-col overflow-hidden rounded-2xl border-2 bg-white text-left shadow-[var(--shadow-card)] transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)] active:scale-[0.99]", TABLE_BORDER[row.table.status] ?? "border-line")}>
      <TableArt src={tableImage(row.table)} className="h-24 w-full">
        <div className="flex h-full flex-col justify-between p-2.5">
          <div className="flex justify-end"><span className="rounded-full bg-white/95 shadow-sm"><TableStatusBadge status={row.table.status} /></span></div>
          <div className="flex items-baseline justify-between gap-2">
            <div className="font-display truncate text-lg font-semibold leading-tight text-white drop-shadow">{row.table.name}</div>
            <div className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.12em] text-white/85">{row.table.game_type.name}</div>
          </div>
        </div>
      </TableArt>
      <div className="flex w-full flex-1 flex-col p-3">
        {running && s ? (
          <div className="w-full space-y-0.5">
            <div className="num text-2xl font-semibold text-sky-700">{duration(elapsed(s, now))}</div>
            <div className="truncate text-xs text-ink-300">{row.customer_name ?? "Walk-in"} · {s.detection_method}</div>
            {row.live_bill && <div className="num text-sm font-semibold text-brass-400">{money(row.live_bill.estimated_total)} so far</div>}
            {s.planned_end_at && <div className={cn("text-xs", endingSoon ? "font-semibold text-amber-700" : "text-ink-400")}>Ends {time(s.planned_end_at)}</div>}
          </div>
        ) : row.next_booking ? (
          <div className="mt-auto text-xs text-amber-800">Next: {time(row.next_booking.start_at)} · {row.next_booking.customer_name}</div>
        ) : (
          <div className="mt-auto text-xs text-ink-400"><span className="num font-semibold text-ink-100">₹{Number(row.table.hourly_rate).toFixed(0)}</span>/hr · tap to start</div>
        )}
        {row.devices.length > 0 && (
          <div className="mt-2 flex items-center gap-1" aria-label="Devices">
            {row.devices.map((d) => <span key={d.device_id} title={`${d.device_id}: ${d.status}`} className={cn("size-2 rounded-full", d.status === "ONLINE" ? "bg-emerald-500" : "bg-red-500")} />)}
            {offline && <span className="text-[10px] text-red-600">device offline</span>}
          </div>
        )}
      </div>
    </button>
  );
}

export function TableBoard({ rows }: { rows: BoardRow[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const row = rows.find((r) => r.table.id === open) ?? null;
  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(200px,1fr))]">
        {rows.map((r) => <TableCard key={r.table.id} row={r} onOpen={() => setOpen(r.table.id)} />)}
      </div>
      {row && <TableSheet row={row} onClose={() => setOpen(null)} />}
    </>
  );
}

function TableSheet({ row, onClose }: { row: BoardRow; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useAuth();
  const [invoiceId, setInvoiceId] = useState<string | null>(null);
  const [customer, setCustomer] = useState<PickedCustomer | null>(null);
  const [planned, setPlanned] = useState("");
  const [override, setOverride] = useState(false);
  const [showItems, setShowItems] = useState(false);
  const [reason, setReason] = useState("");
  const [adjTime, setAdjTime] = useState("");
  const s = row.session;
  const running = s && (s.status === "ACTIVE" || s.status === "PAUSED");
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["board"] });
    qc.invalidateQueries({ queryKey: ["dashboard"] });
  };
  const act = useMutation({
    mutationFn: async (kind: string) => {
      switch (kind) {
        case "start":
          return post("/sessions/start", {
            table_id: row.table.id, customer_id: customer?.id, customer: customer && !customer.id ? { name: customer.name, phone: customer.phone } : undefined,
            planned_minutes: planned ? Number(planned) : undefined, override_reservation: override,
          });
        case "pause": return post(`/sessions/${s!.id}/pause`, { reason: "Paused at counter" });
        case "resume": return post(`/sessions/${s!.id}/resume`);
        case "extend30": return post(`/sessions/${s!.id}/extend`, { minutes: 30 });
        case "extend60": return post(`/sessions/${s!.id}/extend`, { minutes: 60 });
        case "stop": {
          const r = await post<{ invoice: Invoice }>(`/sessions/${s!.id}/stop`);
          setInvoiceId(r.invoice.id);
          return r;
        }
        case "cancel": return post(`/sessions/${s!.id}/cancel`, { reason });
        case "adjust": {
          const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date(s!.started_at ?? Date.now()));
          return post(`/sessions/${s!.id}/adjust`, { started_at: `${today}T${adjTime}:00+05:30`, reason });
        }
        case "maintenance": return post(`/tables/${row.table.id}/status`, { status: "MAINTENANCE", reason: reason || "Maintenance" });
        case "available": return post(`/tables/${row.table.id}/status`, { status: "AVAILABLE" });
      }
    },
    onSuccess: (_d, kind) => {
      refresh();
      toast({ start: "Game started — billing running", stop: "Game ended — bill generated", pause: "Paused", resume: "Resumed", extend30: "Extended +30 min", extend60: "Extended +60 min", cancel: "Session cancelled", adjust: "Start time corrected (audited)", maintenance: "Table set to maintenance", available: "Table back in service" }[kind] ?? "Done");
      if (!["stop", "pause", "resume", "adjust"].includes(kind) && !kind.startsWith("extend")) onClose();
    },
  });
  const errCode = act.error instanceof ApiError ? act.error.code : null;

  if (invoiceId) {
    return (
      <Modal open onClose={onClose} title={`${row.table.name} — Final bill`}>
        <InvoicePanel invoiceId={invoiceId} onDone={() => { refresh(); onClose(); }} />
      </Modal>
    );
  }

  return (
    <Modal open onClose={onClose} title={`${row.table.name} · ${row.table.game_type.name}`}>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <TableStatusBadge status={row.table.status} />
          {row.devices.map((d) => <Badge key={d.device_id} tone={d.status === "ONLINE" ? "green" : "red"}>{d.type.replace("_", " ")} {d.status}</Badge>)}
        </div>

        {running && s ? (
          <>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-xl bg-surface-2 p-3"><div className="text-xs text-ink-400">Customer</div>{row.customer_name ?? "Walk-in"}</div>
              <div className="rounded-xl bg-surface-2 p-3"><div className="text-xs text-ink-400">Started</div>{time(s.started_at)} via {s.detection_method}</div>
              {row.live_bill && <div className="rounded-xl bg-surface-2 p-3"><div className="text-xs text-ink-400">Running bill</div><span className="num text-brass-400">{money(row.live_bill.estimated_total)}</span></div>}
              <div className="rounded-xl bg-surface-2 p-3"><div className="text-xs text-ink-400">Planned end</div>{s.planned_end_at ? time(s.planned_end_at) : "Open"}</div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {s.status === "ACTIVE" ? <Button variant="secondary" size="lg" onClick={() => act.mutate("pause")}>Pause</Button> : <Button size="lg" onClick={() => act.mutate("resume")}>Resume</Button>}
              <Button variant="secondary" size="lg" onClick={() => setShowItems(true)}>Add items</Button>
              <Button variant="secondary" onClick={() => act.mutate("extend30")}>+30 min</Button>
              <Button variant="secondary" onClick={() => act.mutate("extend60")}>+60 min</Button>
            </div>
            <Button variant="brass" size="xl" className="w-full" loading={act.isPending && act.variables === "stop"} onClick={() => act.mutate("stop")}>Stop game &amp; bill</Button>
            <SessionOrder sessionId={s.id} />
            {can("sessions.adjust") && (
              <details className="text-sm">
                <summary className="cursor-pointer text-ink-400">Adjust start time (manager)…</summary>
                <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
                  <Input type="time" aria-label="Correct start time" value={adjTime} onChange={(e) => setAdjTime(e.target.value)} />
                  <Input placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Adjust reason" />
                  <Button variant="secondary" disabled={!adjTime || reason.length < 3} onClick={() => act.mutate("adjust")}>Save</Button>
                </div>
              </details>
            )}
            <details className="text-sm">
              <summary className="cursor-pointer text-ink-400">Cancel without charge…</summary>
              <div className="mt-2 flex gap-2">
                <Input placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Cancel reason" />
                <Button variant="danger" disabled={reason.length < 3} onClick={() => act.mutate("cancel")}>Cancel</Button>
              </div>
              <p className="mt-1 text-xs text-ink-400">Requires manager permission for running games; always audited.</p>
            </details>
          </>
        ) : row.table.status === "MAINTENANCE" || row.table.status === "BLOCKED" ? (
          <Button size="lg" className="w-full" disabled={!can("tables.manage")} onClick={() => act.mutate("available")}>Put back in service</Button>
        ) : (
          <>
            {row.next_booking && (
              <div className="rounded-xl border border-amber-400/30 bg-amber-500/10 p-3 text-sm">
                Booked {time(row.next_booking.start_at)}–{time(row.next_booking.end_at)} for <b>{row.next_booking.customer_name}</b> ({row.next_booking.reference}) · {row.next_booking.status}
              </div>
            )}
            <Field label="Customer (optional for walk-in)"><CustomerPicker value={customer} onChange={setCustomer} /></Field>
            <Field label="Planned time">
              <Select value={planned} onChange={(e) => setPlanned(e.target.value)}>
                <option value="">Open (pay for actual time)</option>
                {[30, 60, 90, 120, 180].map((m) => <option key={m} value={m}>{m} minutes</option>)}
              </Select>
            </Field>
            {errCode === "TABLE_RESERVED" && (
              <label className="flex items-center gap-2 text-sm text-amber-800"><input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} /> Start anyway (reservation override, audited)</label>
            )}
            <Button size="xl" className="w-full" loading={act.isPending && act.variables === "start"} onClick={() => act.mutate("start")}>Start game</Button>
            {can("tables.manage") && (
              <details className="text-sm">
                <summary className="cursor-pointer text-ink-400">Maintenance…</summary>
                <div className="mt-2 flex gap-2">
                  <Input placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Maintenance reason" />
                  <Button variant="secondary" onClick={() => act.mutate("maintenance")}>Set maintenance</Button>
                </div>
              </details>
            )}
          </>
        )}
        <ErrorBox error={act.error} />
      </div>
      {showItems && s && <AddItems sessionId={s.id} onClose={() => setShowItems(false)} />}
    </Modal>
  );
}

function SessionOrder({ sessionId }: { sessionId: string }) {
  const { data } = useQuery({ queryKey: ["order", sessionId], queryFn: () => get<Order | null>(`/sessions/${sessionId}/order`) });
  if (!data || data.items.length === 0) return null;
  return (
    <div className="rounded-xl border border-line p-3 text-sm">
      <div className="mb-1 text-xs uppercase tracking-wide text-ink-400">On this table</div>
      {data.items.filter((i) => i.status === "ACTIVE").map((i) => (
        <div key={i.id} className="flex justify-between"><span>{i.name} × {Number(i.quantity)}</span><span className="num">{money(i.amount)}</span></div>
      ))}
    </div>
  );
}

export function AddItems({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const { branch } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [cart, setCart] = useState<Record<string, number>>({});
  const { data } = useQuery({ queryKey: ["products", branch?.id], queryFn: () => get<ProductStock[]>("/products", { branch_id: branch?.id }) });
  const m = useMutation({
    mutationFn: () => post(`/sessions/${sessionId}/order/items`, { items: Object.entries(cart).filter(([, q]) => q > 0).map(([product_id, quantity]) => ({ product_id, quantity })) }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["order", sessionId] });
      qc.invalidateQueries({ queryKey: ["board"] });
      toast("Items added to table");
      onClose();
    },
  });
  const total = (data ?? []).reduce((s, p) => s + (cart[p.product.id] ?? 0) * Number(p.product.price), 0);
  return (
    <Modal open onClose={onClose} title="Add items to table" wide>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {(data ?? []).map(({ product: p, stock }) => {
          const q = cart[p.id] ?? 0;
          const out = stock !== null && Number(stock) <= q;
          return (
            <div key={p.id} className="rounded-xl border border-line p-2">
              <div className="text-sm font-medium">{p.name}</div>
              <div className="text-xs text-ink-400">{money(p.price)}{stock !== null ? ` · ${Number(stock)} left` : ""}</div>
              <div className="mt-2 flex items-center justify-between">
                <Button size="sm" variant="secondary" aria-label={`Less ${p.name}`} disabled={!q} onClick={() => setCart({ ...cart, [p.id]: q - 1 })}>−</Button>
                <span className="num">{q}</span>
                <Button size="sm" aria-label={`More ${p.name}`} disabled={out} onClick={() => setCart({ ...cart, [p.id]: q + 1 })}>+</Button>
              </div>
            </div>
          );
        })}
      </div>
      <ErrorBox error={m.error} />
      <Button size="lg" className="mt-4 w-full" disabled={!total} loading={m.isPending} onClick={() => m.mutate()}>Add {money(total)}</Button>
    </Modal>
  );
}
