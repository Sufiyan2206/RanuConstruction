/** Receptionist home — answers in seconds: what's free, running, arriving, owing, ending, broken. */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/services/api";
import type { Dashboard as D } from "@/types/api";
import { useBranchId } from "@/hooks/useBranch";
import { Badge, Button, Card, CardTitle, Empty, ErrorBox, Modal, Spinner, Stat, useToast } from "@/components/ui";
import { TableBoard } from "@/components/TableBoard";
import { InvoicePanel } from "@/components/InvoicePanel";
import { StatusBadge } from "@/components/status";
import { money, time } from "@/lib/format";

export default function Dashboard() {
  const branchId = useBranchId();
  const nav = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [invoice, setInvoice] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["dashboard", branchId], queryFn: () => get<D>(`/branches/${branchId}/dashboard`), enabled: !!branchId, refetchInterval: 30000 });
  const checkIn = useMutation({
    mutationFn: (id: string) => post<{ warning: string | null }>(`/bookings/${id}/check-in`),
    onSuccess: (r) => { toast(r.warning ?? "Checked in — table ready"); qc.invalidateQueries({ queryKey: ["dashboard"] }); },
    onError: (e) => toast((e as Error).message, "err"),
  });
  const ack = useMutation({ mutationFn: (id: string) => post(`/alerts/${id}/ack`), onSuccess: () => qc.invalidateQueries({ queryKey: ["dashboard"] }) });

  if (q.isLoading || !q.data) return q.error ? <ErrorBox error={q.error} /> : <Spinner />;
  const d = q.data;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <Stat label="Today's revenue" value={money(d.today_revenue)} tone="good" />
        <Stat label="Today's bookings" value={d.today_bookings} onClick={() => nav("/admin/bookings")} />
        <Stat label="Active tables" value={d.active_tables} />
        <Stat label="Available" value={d.available_tables} tone="good" />
        <Stat label="Active sessions" value={d.active_sessions} />
        <Stat label="Pending payments" value={d.pending_payments.length} tone={d.pending_payments.length ? "warn" : undefined} onClick={() => nav("/admin/billing")} />
        <Stat label="Device errors" value={d.device_errors} tone={d.device_errors ? "bad" : "good"} onClick={() => nav("/admin/devices")} />
        <Stat label="Low stock" value={d.low_stock} tone={d.low_stock ? "warn" : undefined} onClick={() => nav("/admin/inventory")} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <section aria-label="Tables"><TableBoard rows={d.board} /></section>
        <div className="space-y-4">
          <Card>
            <CardTitle>Arriving (next 3h)</CardTitle>
            {d.upcoming_bookings.length ? d.upcoming_bookings.map((b) => (
              <div key={b.id} className="flex items-center justify-between gap-2 border-b border-line py-2 last:border-0">
                <div className="text-sm"><div className="font-medium">{time(b.start_at)} · {b.table.name}</div><div className="text-xs text-ink-400">{b.customer_name} · {b.reference}</div></div>
                {b.status === "CONFIRMED" ? <Button size="sm" loading={checkIn.isPending && checkIn.variables === b.id} onClick={() => checkIn.mutate(b.id)}>Check in</Button> : <StatusBadge status={b.status} />}
              </div>
            )) : <Empty>No arrivals soon.</Empty>}
          </Card>
          {d.ending_soon.length > 0 && (
            <Card><CardTitle>Ending soon</CardTitle>{d.ending_soon.map((e) => <div key={e.session_id} className="text-sm">Table {e.table_number} · ends {time(e.planned_end_at)}</div>)}</Card>
          )}
          <Card>
            <CardTitle>Needs payment</CardTitle>
            {d.pending_payments.length ? d.pending_payments.map((i) => (
              <button key={i.id} onClick={() => setInvoice(i.id)} className="flex w-full justify-between border-b border-line py-2 text-left text-sm last:border-0 hover:text-brass-400">
                <span>{i.number}<span className="block text-xs text-ink-400">{i.customer_name ?? "Walk-in"}</span></span><span className="num font-semibold">{money(i.balance_due)}</span>
              </button>
            )) : <Empty>All bills settled.</Empty>}
          </Card>
          <Card>
            <CardTitle>Alerts</CardTitle>
            {d.alerts.length ? d.alerts.slice(0, 8).map((a) => (
              <div key={a.id} className="flex items-start justify-between gap-2 border-b border-line py-2 text-sm last:border-0">
                <div><Badge tone={a.severity === "CRITICAL" ? "red" : a.severity === "WARNING" ? "amber" : "blue"}>{a.alert_type.replace(/_/g, " ")}</Badge><div className="mt-1 text-ink-300">{a.message}</div></div>
                <Button size="sm" variant="ghost" onClick={() => ack.mutate(a.id)}>OK</Button>
              </div>
            )) : <Empty>No open alerts.</Empty>}
          </Card>
        </div>
      </div>
      {invoice && <Modal open onClose={() => setInvoice(null)} title="Bill"><InvoicePanel invoiceId={invoice} onDone={() => setInvoice(null)} /></Modal>}
    </div>
  );
}
