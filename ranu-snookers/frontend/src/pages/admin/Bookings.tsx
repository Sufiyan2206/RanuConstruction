import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/services/api";
import type { Booking, Page, Table } from "@/types/api";
import { useBranchId } from "@/hooks/useBranch";
import { Button, Card, DataTable, ErrorBox, Field, Input, Modal, Select, Td, useToast } from "@/components/ui";
import { StatusBadge } from "@/components/status";
import { CustomerPicker, type PickedCustomer } from "@/components/CustomerPicker";
import { localToIso, minutesLabel, money, time, todayLocal, dateTime } from "@/lib/format";

export default function Bookings() {
  const branchId = useBranchId();
  const qc = useQueryClient();
  const toast = useToast();
  const [day, setDay] = useState(todayLocal());
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const [cancelFor, setCancelFor] = useState<Booking | null>(null);
  const [resched, setResched] = useState<Booking | null>(null);
  const q = useQuery({
    queryKey: ["bookings", branchId, day, status],
    queryFn: () => get<Page<Booking>>("/bookings", { branch_id: branchId, from: localToIso(day, "00:00"), to: localToIso(todayPlus(day, 1), "06:00"), status: status || undefined, size: 200 }),
    enabled: !!branchId,
  });
  const act = useMutation({
    mutationFn: ({ id, kind }: { id: string; kind: "check-in" | "no-show" }) => post<{ warning?: string }>(`/bookings/${id}/${kind}`),
    onSuccess: (r, v) => { toast(r?.warning ?? (v.kind === "check-in" ? "Checked in" : "Marked no-show (deposit retained)")); qc.invalidateQueries({ queryKey: ["bookings"] }); },
    onError: (e) => toast((e as Error).message, "err"),
  });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold">Bookings</h1>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Business day"><Input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
          <Field label="Status"><Select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option>{["HELD", "CONFIRMED", "CHECKED_IN", "IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_SHOW", "EXPIRED"].map((s) => <option key={s}>{s}</option>)}</Select></Field>
          <Button onClick={() => setCreating(true)}>+ Phone / counter booking</Button>
        </div>
      </div>
      <Card className="p-0 sm:p-0">
        <DataTable head={["Time", "Table", "Customer", "Ref", "Status", "Paid / Total", "Source", ""]} empty={q.data?.items.length === 0}>
          {(q.data?.items ?? []).sort((a, b) => a.start_at.localeCompare(b.start_at)).map((b) => (
            <tr key={b.id}>
              <Td className="whitespace-nowrap">{time(b.start_at)}–{time(b.end_at)}</Td><Td>{b.table.name}</Td>
              <Td>{b.customer_name}<div className="text-xs text-ink-400">{b.customer_phone}</div></Td>
              <Td className="font-mono text-xs">{b.reference}</Td><Td><StatusBadge status={b.status} /></Td>
              <Td className="num">{money(b.amount_paid)} / {money(b.booking_amount)}</Td><Td className="text-xs">{b.source}</Td>
              <Td className="whitespace-nowrap">
                {b.status === "CONFIRMED" && (
                  <div className="flex gap-1">
                    <Button size="sm" onClick={() => act.mutate({ id: b.id, kind: "check-in" })}>Check in</Button>
                    <Button size="sm" variant="ghost" onClick={() => setResched(b)}>Move</Button>
                    <Button size="sm" variant="ghost" onClick={() => setCancelFor(b)}>Cancel</Button>
                    <Button size="sm" variant="ghost" onClick={() => act.mutate({ id: b.id, kind: "no-show" })}>No-show</Button>
                  </div>
                )}
              </Td>
            </tr>
          ))}
        </DataTable>
      </Card>
      {creating && <NewBooking onClose={() => setCreating(false)} />}
      {cancelFor && <CancelBooking b={cancelFor} onClose={() => setCancelFor(null)} />}
      {resched && <Reschedule b={resched} onClose={() => setResched(null)} />}
    </div>
  );
}

function todayPlus(day: string, n: number) {
  const d = new Date(`${day}T12:00:00+05:30`);
  d.setDate(d.getDate() + n);
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(d);
}

function NewBooking({ onClose }: { onClose: () => void }) {
  const branchId = useBranchId();
  const qc = useQueryClient();
  const toast = useToast();
  const tables = useQuery({ queryKey: ["tables", branchId], queryFn: () => get<Table[]>(`/branches/${branchId}/tables`) });
  const [f, setF] = useState({ table_id: "", day: todayLocal(), time: "18:00", duration: "60", deposit_method: "", deposit_amount: "", deposit_reference: "" });
  const [customer, setCustomer] = useState<PickedCustomer | null>(null);
  const m = useMutation({
    mutationFn: () => post<Booking>("/bookings", {
      branch_id: branchId, table_id: f.table_id || tables.data?.[0]?.id, start_at: localToIso(f.day, f.time), duration_minutes: Number(f.duration), source: "PHONE",
      customer_id: customer?.id, customer: customer && !customer.id ? { name: customer.name, phone: customer.phone } : undefined,
      deposit_method: f.deposit_method || undefined, deposit_amount: f.deposit_amount || undefined, deposit_reference: f.deposit_reference || undefined,
    }),
    onSuccess: (b) => { toast(`Booked ${b.reference}`); qc.invalidateQueries({ queryKey: ["bookings"] }); onClose(); },
  });
  return (
    <Modal open onClose={onClose} title="New booking">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Customer" className="sm:col-span-2"><CustomerPicker value={customer} onChange={setCustomer} /></Field>
        <Field label="Table"><Select value={f.table_id} onChange={(e) => setF({ ...f, table_id: e.target.value })}>{(tables.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name} · {t.game_type.name}</option>)}</Select></Field>
        <Field label="Date"><Input type="date" value={f.day} onChange={(e) => setF({ ...f, day: e.target.value })} /></Field>
        <Field label="Start"><Input type="time" step={900} value={f.time} onChange={(e) => setF({ ...f, time: e.target.value })} /></Field>
        <Field label="Duration"><Select value={f.duration} onChange={(e) => setF({ ...f, duration: e.target.value })}>{[30, 60, 90, 120, 180, 240].map((d) => <option key={d} value={d}>{minutesLabel(d)}</option>)}</Select></Field>
        <Field label="Deposit method"><Select value={f.deposit_method} onChange={(e) => setF({ ...f, deposit_method: e.target.value })}><option value="">No deposit</option><option>CASH</option><option>UPI</option><option>CARD</option></Select></Field>
        {f.deposit_method && <Field label="Deposit ₹"><Input inputMode="decimal" value={f.deposit_amount} onChange={(e) => setF({ ...f, deposit_amount: e.target.value })} /></Field>}
        {(f.deposit_method === "UPI" || f.deposit_method === "CARD") && <Field label="Reference"><Input value={f.deposit_reference} onChange={(e) => setF({ ...f, deposit_reference: e.target.value })} /></Field>}
      </div>
      <ErrorBox error={m.error} />
      <Button className="mt-4 w-full" size="lg" disabled={!customer} loading={m.isPending} onClick={() => m.mutate()}>Confirm booking</Button>
    </Modal>
  );
}

function CancelBooking({ b, onClose }: { b: Booking; onClose: () => void }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const m = useMutation({ mutationFn: () => post<Booking>(`/bookings/${b.id}/cancel`, { reason }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["bookings"] }); onClose(); } });
  return (
    <Modal open onClose={onClose} title={`Cancel ${b.reference}`}>
      <p className="mb-3 text-sm text-ink-300">{b.customer_name} · {dateTime(b.start_at)}. Deposit paid {money(b.amount_paid)}; refund is calculated from the cancellation policy.</p>
      <Field label="Reason"><Input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <ErrorBox error={m.error} />
      <Button variant="danger" className="mt-4 w-full" disabled={reason.length < 3} loading={m.isPending} onClick={() => m.mutate()}>Cancel booking</Button>
    </Modal>
  );
}

function Reschedule({ b, onClose }: { b: Booking; onClose: () => void }) {
  const qc = useQueryClient();
  const [day, setDay] = useState(todayLocal());
  const [t, setT] = useState("19:00");
  const m = useMutation({ mutationFn: () => post<Booking>(`/bookings/${b.id}/reschedule`, { start_at: localToIso(day, t), reason: "Rescheduled at counter" }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["bookings"] }); onClose(); } });
  return (
    <Modal open onClose={onClose} title={`Move ${b.reference}`}>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Date"><Input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
        <Field label="Start"><Input type="time" step={900} value={t} onChange={(e) => setT(e.target.value)} /></Field>
      </div>
      <ErrorBox error={m.error} />
      <Button className="mt-4 w-full" loading={m.isPending} onClick={() => m.mutate()}>Move booking</Button>
    </Modal>
  );
}
