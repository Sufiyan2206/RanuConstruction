/** Customer self-service: my bookings (cancel/reschedule), invoices, membership; QR "Start game" page. */
import { useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/services/api";
import type { Booking, CustomerProfile, Invoice, Page, PublicTable } from "@/types/api";
import { useAuth } from "@/stores/auth";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Spinner } from "@/components/ui";
import { StatusBadge } from "@/components/status";
import { dateTime, minutesLabel, money, time } from "@/lib/format";

export function MyBookings() {
  const { me, ready, logout } = useAuth();
  const qc = useQueryClient();
  const bookings = useQuery({ queryKey: ["bookings", "mine"], queryFn: () => get<Page<Booking>>("/bookings", { size: 50 }), enabled: !!me });
  const profile = useQuery({ queryKey: ["profile", "me"], queryFn: () => get<CustomerProfile>("/customers/me/profile"), enabled: !!me?.user.customer_id });
  const invoices = useQuery({ queryKey: ["invoices", "mine"], queryFn: () => get<Invoice[]>(`/customers/${me!.user.customer_id}/invoices`), enabled: !!me?.user.customer_id });
  const cancel = useMutation({
    mutationFn: (id: string) => post(`/bookings/${id}/cancel`, { reason: "Cancelled by customer online" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bookings"] }),
  });
  if (!ready) return <div className="grid place-items-center p-20"><Spinner /></div>;
  if (!me) return <Navigate to="/login?next=/my/bookings" replace />;
  const p = profile.data;
  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-10">
      <div className="flex items-center justify-between">
        <h1 className="font-[family-name:var(--font-display)] text-3xl">Hi, {me.user.full_name.split(" ")[0]}</h1>
        <Button variant="ghost" onClick={logout}>Sign out</Button>
      </div>
      {p && (
        <div className="grid gap-3 sm:grid-cols-4">
          <Card><div className="text-xs text-ink-400">Visits</div><div className="num text-2xl">{p.total_visits}</div></Card>
          <Card><div className="text-xs text-ink-400">Loyalty points</div><div className="num text-2xl text-brass-400">{p.loyalty_points}</div></Card>
          <Card><div className="text-xs text-ink-400">Membership</div><div className="text-sm">{p.membership ? `${p.membership.plan.name} · ${minutesLabel(p.membership.minutes_remaining)} left` : "—"}</div></Card>
          <Card><div className="text-xs text-ink-400">Referral code</div><div className="font-mono text-lg">{p.customer.referral_code}</div></Card>
        </div>
      )}
      <Card>
        <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">My bookings</h2><Link to="/book" className="text-sm text-brass-400 underline">Book a table</Link></div>
        {bookings.data?.items.length ? (
          <ul className="divide-y divide-line">
            {bookings.data.items.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                <div>
                  <div className="font-medium">{b.table.name} · {dateTime(b.start_at)}–{time(b.end_at)}</div>
                  <div className="text-xs text-ink-400">{b.reference} · paid {money(b.amount_paid)} · due {money(b.remaining_amount)}</div>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={b.status} />
                  {b.status === "HELD" && <Link to={`/booking/${b.reference}`} className="text-sm text-brass-400 underline">Pay</Link>}
                  {b.status === "CONFIRMED" && <Button size="sm" variant="ghost" loading={cancel.isPending && cancel.variables === b.id} onClick={() => confirm("Cancel this booking? Deposit refund follows the club policy.") && cancel.mutate(b.id)}>Cancel</Button>}
                </div>
              </li>
            ))}
          </ul>
        ) : <Empty>No bookings yet.</Empty>}
        <ErrorBox error={cancel.error} />
      </Card>
      <Card>
        <h2 className="mb-3 font-semibold">My bills</h2>
        {invoices.data?.length ? (
          <ul className="divide-y divide-line text-sm">
            {invoices.data.map((i) => <li key={i.id} className="flex justify-between py-2"><span>{i.number} · {dateTime(i.issued_at)}</span><span className="num">{money(i.total)} <StatusBadge status={i.status} /></span></li>)}
          </ul>
        ) : <Empty>No bills yet.</Empty>}
      </Card>
    </div>
  );
}

export function QrStart() {
  const { token = "" } = useParams();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const info = useQuery({ queryKey: ["qr", token], queryFn: () => get<{ table: PublicTable; status: string; session_running: boolean; started_at: string | null }>(`/public/qr/${token}`), refetchInterval: 10000 });
  const start = useMutation({ mutationFn: () => post<{ outcome: string }>(`/public/qr/${token}/start`, { name, phone }), onSuccess: () => info.refetch() });
  if (info.isLoading) return <div className="grid place-items-center p-20"><Spinner /></div>;
  if (!info.data) return <div className="p-10 text-center"><ErrorBox error={info.error ?? "Unknown table"} /></div>;
  const d = info.data;
  return (
    <div className="mx-auto max-w-sm px-4 py-12">
      <Card className="space-y-4 text-center">
        <div className="text-xs uppercase tracking-widest text-ink-400">RANU Snookers</div>
        <div className="text-3xl font-bold">{d.table.name}</div>
        <Badge tone={d.session_running ? "blue" : "green"}>{d.session_running ? "Game running" : d.status.toLowerCase()}</Badge>
        {d.session_running ? (
          <p className="text-sm text-ink-300">Started at {time(d.started_at)}. Enjoy your game! Ask the counter to stop &amp; pay.</p>
        ) : (
          <>
            <p className="text-sm text-ink-300">Rate {money(d.table.hourly_rate)}/hr. Billing starts when you tap Start.</p>
            <Field label="Your name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Mobile"><Input inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
            <Button size="xl" className="w-full" loading={start.isPending} disabled={phone.replace(/\D/g, "").length < 10} onClick={() => start.mutate()}>Start game</Button>
            {start.data && start.data.outcome !== "SESSION_STARTED" && <div className="text-sm text-amber-800">Request sent to the counter — staff will start your table.</div>}
            <ErrorBox error={start.error} />
          </>
        )}
      </Card>
    </div>
  );
}
