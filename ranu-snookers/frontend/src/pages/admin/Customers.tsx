import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/services/api";
import type { Customer, CustomerProfile, LedgerEntry, Membership, Page, Plan } from "@/types/api";
import { useBranchId } from "@/hooks/useBranch";
import { useAuth } from "@/stores/auth";
import { Badge, Button, Card, CardTitle, DataTable, ErrorBox, Field, Input, Modal, Select, Stat, Tabs, Td, useToast } from "@/components/ui";
import { StatusBadge } from "@/components/status";
import { date, dateTime, minutesLabel, money, num, waLink } from "@/lib/format";

export default function Customers() {
  const branchId = useBranchId();
  const [tab, setTab] = useState<"all" | "dues">("all");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const list = useQuery({ queryKey: ["customers", q], queryFn: () => get<Page<Customer>>("/customers", { q, size: 50 }) });
  const dues = useQuery({ queryKey: ["outstanding", branchId], queryFn: () => get<{ customer_id: string; name: string; phone: string; balance: string }[]>(`/branches/${branchId}/outstanding`), enabled: tab === "dues" });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Customers</h1>
        <div className="flex gap-2"><Tabs value={tab} onChange={setTab} items={[{ value: "all", label: "All customers" }, { value: "dues", label: "Outstanding dues" }]} /><Button onClick={() => setAdding(true)}>+ Add</Button></div>
      </div>
      {tab === "all" ? (
        <>
          <Input placeholder="Search by name, phone or email" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search" />
          <Card className="p-0 sm:p-0">
            <DataTable head={["Name", "Phone", "Visits", "Spend", "Points", "Last visit"]}>
              {(list.data?.items ?? []).map((c) => (
                <tr key={c.id} className="cursor-pointer hover:bg-surface-2" onClick={() => setOpen(c.id)}>
                  <Td>{c.name}</Td><Td>{c.phone}</Td><Td>{c.total_visits}</Td><Td className="num">{money(c.total_spend)}</Td><Td>{c.loyalty_points}</Td><Td>{date(c.last_visit_at)}</Td>
                </tr>
              ))}
            </DataTable>
          </Card>
        </>
      ) : (
        <Card className="p-0 sm:p-0">
          <DataTable head={["Customer", "Phone", "Outstanding", ""]} empty={dues.data?.length === 0}>
            {(dues.data ?? []).map((d) => (
              <tr key={d.customer_id}>
                <Td>{d.name}</Td><Td>{d.phone}</Td><Td className="num font-semibold text-amber-700">{money(d.balance)}</Td>
                <Td className="flex gap-2"><Button size="sm" onClick={() => setOpen(d.customer_id)}>Open</Button>
                  <a className="text-xs text-brass-400 underline" target="_blank" rel="noreferrer" href={waLink(d.phone, `Hi ${d.name}, a gentle reminder: your RANU Snookers balance is ${money(d.balance)}. Thank you!`)}>WhatsApp reminder</a></Td>
              </tr>
            ))}
          </DataTable>
        </Card>
      )}
      {open && <CustomerModal id={open} onClose={() => setOpen(null)} />}
      {adding && <AddCustomer onClose={() => setAdding(false)} />}
    </div>
  );
}

function AddCustomer({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [f, setF] = useState({ name: "", phone: "", email: "", referral_code_used: "", marketing_opt_in: false });
  const m = useMutation({ mutationFn: () => post("/customers", { ...f, email: f.email || undefined, referral_code_used: f.referral_code_used || undefined }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["customers"] }); onClose(); } });
  return (
    <Modal open onClose={onClose} title="New customer">
      <div className="grid gap-3">
        <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Mobile (WhatsApp)"><Input inputMode="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} /></Field>
        <Field label="Email"><Input value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Referral code (optional)"><Input value={f.referral_code_used} onChange={(e) => setF({ ...f, referral_code_used: e.target.value })} /></Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.marketing_opt_in} onChange={(e) => setF({ ...f, marketing_opt_in: e.target.checked })} /> Agrees to receive offers</label>
      </div>
      <ErrorBox error={m.error} />
      <Button className="mt-4 w-full" loading={m.isPending} onClick={() => m.mutate()}>Save</Button>
    </Modal>
  );
}

export function CustomerModal({ id, onClose }: { id: string; onClose: () => void }) {
  const branchId = useBranchId();
  const { can } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const prof = useQuery({ queryKey: ["customer", id], queryFn: () => get<CustomerProfile>(`/customers/${id}`) });
  const ledger = useQuery({ queryKey: ["ledger", id], queryFn: () => get<LedgerEntry[]>(`/customers/${id}/ledger`) });
  const [pay, setPay] = useState({ amount: "", method: "CASH" });
  const [opening, setOpening] = useState("");
  const payDues = useMutation({ mutationFn: () => post(`/customers/${id}/pay-dues`, { branch_id: branchId, amount: pay.amount, method: pay.method }), onSuccess: () => { toast("Due payment recorded"); qc.invalidateQueries({ queryKey: ["customer", id] }); qc.invalidateQueries({ queryKey: ["ledger", id] }); qc.invalidateQueries({ queryKey: ["outstanding"] }); } });
  const addOpening = useMutation({ mutationFn: () => post(`/customers/${id}/opening-due`, { branch_id: branchId, amount: opening, note: "Opening balance" }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["customer", id] }); qc.invalidateQueries({ queryKey: ["ledger", id] }); } });
  const p = prof.data;
  return (
    <Modal open onClose={onClose} title={p?.customer.name ?? "Customer"} wide>
      {p && (
        <div className="space-y-4">
          <div className="text-sm text-ink-400">{p.customer.phone} · {p.customer.email ?? "no email"} · since {date(p.customer.created_at)} · referral {p.customer.referral_code}</div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Total visits" value={p.total_visits} /><Stat label="Total spend" value={money(p.total_spend)} />
            <Stat label="Avg session" value={`${p.average_session_minutes}m`} /><Stat label="Favourite game" value={p.favorite_game ?? "—"} />
            <Stat label="Membership" value={p.membership ? p.membership.plan.name : "—"} sub={p.membership ? `${minutesLabel(p.membership.minutes_remaining)} left · till ${p.membership.expires_on}` : undefined} />
            <Stat label="Last visit" value={date(p.last_visit_at)} /><Stat label="Loyalty points" value={p.loyalty_points} />
            <Stat label="Outstanding" value={money(p.outstanding)} tone={num(p.outstanding) > 0 ? "warn" : "good"} />
          </div>
          {num(p.outstanding) > 0 && can("billing.operate") && (
            <div className="flex flex-wrap items-end gap-2 rounded-xl border border-line p-3">
              <Field label="Collect dues ₹"><Input inputMode="decimal" value={pay.amount} onChange={(e) => setPay({ ...pay, amount: e.target.value })} /></Field>
              <Field label="Method"><Select value={pay.method} onChange={(e) => setPay({ ...pay, method: e.target.value })}><option>CASH</option><option>UPI</option><option>CARD</option></Select></Field>
              <Button loading={payDues.isPending} onClick={() => payDues.mutate()}>Record payment</Button>
            </div>
          )}
          <ErrorBox error={payDues.error} />
          <Card>
            <CardTitle action={can("customers.manage") && (
              <span className="flex gap-2"><Input className="h-8 w-28" placeholder="Opening ₹" value={opening} onChange={(e) => setOpening(e.target.value)} /><Button size="sm" variant="secondary" onClick={() => addOpening.mutate()}>Add opening due</Button></span>
            )}>Dues ledger</CardTitle>
            <DataTable head={["When", "Type", "Amount", "Note"]} empty={ledger.data?.length === 0}>
              {(ledger.data ?? []).map((l) => <tr key={l.id}><Td>{dateTime(l.created_at)}</Td><Td><Badge>{l.entry_type}</Badge></Td><Td className="num">{money(l.amount)}</Td><Td>{l.note}</Td></tr>)}
            </DataTable>
          </Card>
        </div>
      )}
    </Modal>
  );
}

/** Membership plans + sell / renew / cards / statements. */
export function Memberships() {
  const branchId = useBranchId();
  const { can } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"members" | "expiring" | "plans">("members");
  const [selling, setSelling] = useState(false);
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => get<Plan[]>("/membership-plans") });
  const mems = useQuery({ queryKey: ["memberships", tab], queryFn: () => get<Membership[]>("/memberships", tab === "expiring" ? { expiring_days: 7 } : { status: "ACTIVE" }) });
  const [sell, setSell] = useState({ customer_id: "", plan_id: "", payment_method: "CASH", reference: "", card_uid: "" });
  const [q, setQ] = useState("");
  const found = useQuery({ queryKey: ["customers", q], queryFn: () => get<Page<Customer>>("/customers", { q, size: 6 }), enabled: selling && q.length >= 2 });
  const sellM = useMutation({
    mutationFn: () => post<Membership>("/memberships", { branch_id: branchId, ...sell, reference: sell.reference || undefined, card_uid: sell.card_uid || undefined }),
    onSuccess: (m) => { toast(`Membership ${m.code} activated`); qc.invalidateQueries({ queryKey: ["memberships"] }); setSelling(false); },
  });
  const renew = useMutation({ mutationFn: (id: string) => post(`/memberships/${id}/renew`, { payment_method: "CASH" }), onSuccess: () => { toast("Renewed"); qc.invalidateQueries({ queryKey: ["memberships"] }); } });
  const card = useMutation({ mutationFn: ({ id, uid }: { id: string; uid: string }) => post(`/memberships/${id}/card`, { card_uid: uid }), onSuccess: () => { toast("Card linked"); qc.invalidateQueries({ queryKey: ["memberships"] }); } });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Memberships</h1>
        <div className="flex gap-2">
          <Tabs value={tab} onChange={setTab} items={[{ value: "members", label: "Active" }, { value: "expiring", label: "Expiring (7d)" }, { value: "plans", label: "Plans" }]} />
          {can("memberships.manage") && <Button onClick={() => setSelling(true)}>+ Sell membership</Button>}
        </div>
      </div>
      {tab === "plans" ? (
        <div className="grid gap-3 md:grid-cols-3">
          {(plans.data ?? []).map((p) => (
            <Card key={p.id}><Badge>{p.tier}</Badge><div className="mt-2 text-lg font-semibold">{p.name}</div><div className="num text-2xl text-brass-400">{money(p.price)}</div>
              <div className="text-xs text-ink-400">{p.validity_days} days · {p.included_minutes ? minutesLabel(p.included_minutes) : "no prepaid time"} · deducts in {p.deduction_block_minutes}-min blocks · table −{p.table_discount_percent}% · F&B −{p.product_discount_percent}%</div></Card>
          ))}
        </div>
      ) : (
        <Card className="p-0 sm:p-0">
          <DataTable head={["Code", "Customer", "Plan", "Balance", "Expires", "Card", "Status", ""]} empty={mems.data?.length === 0}>
            {(mems.data ?? []).map((m) => (
              <tr key={m.id}>
                <Td className="font-mono">{m.code}</Td><Td>{m.customer?.name}<div className="text-xs text-ink-400">{m.customer?.phone}</div></Td><Td>{m.plan.name}</Td>
                <Td>{m.minutes_total ? `${minutesLabel(m.minutes_remaining)} / ${minutesLabel(m.minutes_total)}` : "—"}</Td><Td>{m.expires_on}</Td>
                <Td className="font-mono text-xs">{m.card_uid ?? <Button size="sm" variant="ghost" onClick={() => { const uid = prompt("Tap card on reader / type card UID"); if (uid) card.mutate({ id: m.id, uid }); }}>Link card</Button>}</Td>
                <Td><StatusBadge status={m.status} /></Td>
                <Td><Button size="sm" variant="secondary" onClick={() => renew.mutate(m.id)}>Renew</Button></Td>
              </tr>
            ))}
          </DataTable>
        </Card>
      )}
      <Modal open={selling} onClose={() => setSelling(false)} title="Sell membership">
        <div className="grid gap-3">
          <Field label="Customer">
            <Input placeholder="Search name/phone" value={q} onChange={(e) => setQ(e.target.value)} />
            <div className="mt-1 flex flex-wrap gap-1">{(found.data?.items ?? []).map((c) => (
              <button key={c.id} onClick={() => setSell({ ...sell, customer_id: c.id })} className={`rounded-full px-2 py-1 text-xs ${sell.customer_id === c.id ? "bg-brass-500 text-felt-950 font-semibold" : "bg-surface-2"}`}>{c.name} · {c.phone}</button>
            ))}</div>
          </Field>
          <Field label="Plan"><Select value={sell.plan_id} onChange={(e) => setSell({ ...sell, plan_id: e.target.value })}><option value="">Choose…</option>{(plans.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name} · {money(p.price)}</option>)}</Select></Field>
          <Field label="Payment"><Select value={sell.payment_method} onChange={(e) => setSell({ ...sell, payment_method: e.target.value })}><option>CASH</option><option>UPI</option><option>CARD</option><option value="CREDIT">Credit (Due)</option></Select></Field>
          <Field label="Reference (UPI/card)"><Input value={sell.reference} onChange={(e) => setSell({ ...sell, reference: e.target.value })} /></Field>
          <Field label="RFID/NFC card UID (optional)" hint="Tap the card on a USB reader with this field focused"><Input value={sell.card_uid} onChange={(e) => setSell({ ...sell, card_uid: e.target.value })} /></Field>
        </div>
        <ErrorBox error={sellM.error} />
        <Button className="mt-4 w-full" disabled={!sell.customer_id || !sell.plan_id} loading={sellM.isPending} onClick={() => sellM.mutate()}>Activate membership</Button>
      </Modal>
    </div>
  );
}
