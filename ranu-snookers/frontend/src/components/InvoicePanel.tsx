/** Invoice view + split payment + discount request + receipt print / WhatsApp share. */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/services/api";
import type { Invoice, PaymentMethod } from "@/types/api";
import { Button, ErrorBox, Field, Input, Select, useToast } from "@/components/ui";
import { StatusBadge } from "@/components/status";
import { dateTime, money, num, waLink } from "@/lib/format";
import { useAuth } from "@/stores/auth";

const METHODS: { v: PaymentMethod; label: string }[] = [
  { v: "CASH", label: "Cash" }, { v: "UPI", label: "UPI" }, { v: "CARD", label: "Card" }, { v: "WALLET", label: "Wallet" }, { v: "CREDIT", label: "Credit (Due)" },
];

type Split = { method: PaymentMethod; amount: string; reference: string };

export function InvoicePanel({ invoiceId, onDone }: { invoiceId: string; onDone?: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { branch, can } = useAuth();
  const { data: inv, error } = useQuery({ queryKey: ["invoice", invoiceId], queryFn: () => get<Invoice>(`/invoices/${invoiceId}`) });
  const [splits, setSplits] = useState<Split[]>([]);
  const [discount, setDiscount] = useState({ amount: "", reason: "" });
  const idemKey = useMemo(() => crypto.randomUUID(), []);

  const balance = num(inv?.balance_due);
  const rows = splits.length ? splits : [{ method: "CASH" as PaymentMethod, amount: balance > 0 ? String(balance) : "", reference: "" }];
  const total = rows.reduce((s, r) => s + num(r.amount), 0);

  const pay = useMutation({
    mutationFn: () => post<Invoice>(`/invoices/${invoiceId}/pay`, { splits: rows.filter((r) => num(r.amount) > 0).map((r) => ({ method: r.method, amount: r.amount, reference: r.reference || undefined })) },
      { headers: { "Idempotency-Key": idemKey } }),
    onSuccess: (x) => {
      qc.setQueryData(["invoice", invoiceId], x);
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast(x.status === "PAID" ? "Payment received — bill settled" : "Partial payment recorded");
      if (x.status === "PAID") onDone?.();
    },
  });
  const disc = useMutation({
    mutationFn: () => post<{ applied: boolean; invoice: Invoice }>(`/invoices/${invoiceId}/discount`, discount),
    onSuccess: (r) => {
      qc.setQueryData(["invoice", invoiceId], r.invoice);
      toast(r.applied ? "Discount applied" : "Discount sent to manager for approval");
      setDiscount({ amount: "", reason: "" });
    },
  });

  if (error) return <ErrorBox error={error} />;
  if (!inv) return <div className="text-sm text-ink-400">Loading bill…</div>;

  const setRow = (i: number, patch: Partial<Split>) => setSplits(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const receiptText = `${branch?.name ?? "RANU Snookers"}\nBill ${inv.number}\n${inv.lines.map((l) => `${l.description}: ${money(l.amount)}`).join("\n")}\nTotal: ${money(inv.total)}\nPaid: ${money(num(inv.amount_paid) + num(inv.deposit_applied))}\nThank you!`;

  return (
    <div className="space-y-4">
      <div className="print-area space-y-3">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-xs text-ink-400">{branch?.name}</div>
            <div className="font-semibold">Bill {inv.number}</div>
            <div className="text-xs text-ink-400">{dateTime(inv.issued_at)}{inv.customer_name ? ` · ${inv.customer_name}` : ""}</div>
          </div>
          <StatusBadge status={inv.status} />
        </div>
        <ul className="divide-y divide-line rounded-lg border border-line text-sm">
          {inv.lines.map((l, i) => (
            <li key={i} className="flex justify-between gap-3 px-3 py-2">
              <span className={l.line_type === "DISCOUNT" ? "text-emerald-700" : ""}>{l.description}{l.line_type === "PRODUCT" && num(l.quantity) > 1 ? ` × ${num(l.quantity)}` : ""}</span>
              <span className="num whitespace-nowrap">{money(l.amount)}</span>
            </li>
          ))}
          {inv.adjustments.map((a, i) => (
            <li key={`a${i}`} className="flex justify-between gap-3 px-3 py-2 text-emerald-700"><span>{a.reason}</span><span className="num">{money(a.amount)}</span></li>
          ))}
        </ul>
        <dl className="num grid grid-cols-2 gap-y-1 text-sm">
          {num(inv.tax_total) > 0 && (<><dt className="text-ink-400">Tax (incl.)</dt><dd className="text-right">{money(inv.tax_total)}</dd></>)}
          <dt className="font-semibold">Total</dt><dd className="text-right font-semibold">{money(inv.total)}</dd>
          {num(inv.deposit_applied) > 0 && (<><dt className="text-ink-400">Deposit paid online</dt><dd className="text-right">− {money(inv.deposit_applied)}</dd></>)}
          {num(inv.amount_paid) > 0 && (<><dt className="text-ink-400">Paid</dt><dd className="text-right">− {money(inv.amount_paid)}</dd></>)}
          <dt className="text-lg font-bold text-brass-400">Balance due</dt><dd className="text-right text-lg font-bold text-brass-400">{money(inv.balance_due)}</dd>
        </dl>
      </div>

      {balance > 0 && inv.status !== "VOID" && can("billing.operate") && (
        <div className="space-y-3 rounded-xl border border-line p-3">
          <div className="text-sm font-medium">Take payment</div>
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr] gap-2 sm:grid-cols-[1fr_1fr_1.2fr]">
              <Select aria-label="Method" value={r.method} onChange={(e) => setRow(i, { method: e.target.value as PaymentMethod })}>
                {METHODS.map((m) => <option key={m.v} value={m.v}>{m.label}</option>)}
              </Select>
              <Input aria-label="Amount" inputMode="decimal" value={r.amount} onChange={(e) => setRow(i, { amount: e.target.value })} />
              {(r.method === "UPI" || r.method === "CARD") && <Input aria-label="Reference" placeholder="Txn / UTR ref" value={r.reference} onChange={(e) => setRow(i, { reference: e.target.value })} className="col-span-2 sm:col-span-1" />}
            </div>
          ))}
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setSplits([...rows, { method: "UPI", amount: String(Math.max(0, balance - total)), reference: "" }])}>+ Split payment</Button>
            <span className="num ml-auto text-sm text-ink-300">Entered {money(total)} / {money(balance)}</span>
          </div>
          <ErrorBox error={pay.error} />
          <Button size="lg" className="w-full" loading={pay.isPending} disabled={total <= 0 || total > balance + 0.001} onClick={() => pay.mutate()}>Collect {money(total)}</Button>
        </div>
      )}

      {balance > 0 && inv.status !== "VOID" && (
        <details className="rounded-xl border border-line p-3 text-sm">
          <summary className="cursor-pointer text-ink-300">Discount / correction</summary>
          <div className="mt-3 grid gap-2 sm:grid-cols-[120px_1fr_auto]">
            <Input aria-label="Discount amount" placeholder="₹" inputMode="decimal" value={discount.amount} onChange={(e) => setDiscount({ ...discount, amount: e.target.value })} />
            <Input aria-label="Reason" placeholder="Reason (required)" value={discount.reason} onChange={(e) => setDiscount({ ...discount, reason: e.target.value })} />
            <Button variant="secondary" loading={disc.isPending} disabled={!num(discount.amount) || discount.reason.length < 3} onClick={() => disc.mutate()}>Apply</Button>
          </div>
          <p className="mt-2 text-xs text-ink-400">Above your limit it goes to a manager for approval. Original bill lines are never changed — a credit note is added.</p>
          <ErrorBox error={disc.error} />
        </details>
      )}

      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => window.print()}>Print receipt</Button>
        <a className="inline-flex h-10 items-center rounded-lg border border-line px-4 text-sm hover:border-brass-500" target="_blank" rel="noreferrer" href={waLink("", receiptText)}>Share on WhatsApp</a>
      </div>
    </div>
  );
}

export function FieldRow({ label, children }: { label: string; children: React.ReactNode }) {
  return <Field label={label}>{children}</Field>;
}
