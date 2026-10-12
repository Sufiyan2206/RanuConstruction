/** Inventory · Shift & Expenses · Approvals & Alerts. */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/services/api";
import type { Alert, Approval, Expense, ExpenseCategory, InventoryTxn, Page, ProductStock, Shift } from "@/types/api";
import { useBranchId } from "@/hooks/useBranch";
import { useAuth } from "@/stores/auth";
import { Badge, Button, Card, CardTitle, DataTable, Empty, ErrorBox, Field, Input, Select, Stat, Tabs, Td, useToast } from "@/components/ui";
import { StatusBadge } from "@/components/status";
import { dateTime, money, num, todayLocal } from "@/lib/format";

export function Inventory() {
  const branchId = useBranchId();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<"stock" | "ledger">("stock");
  const stock = useQuery({ queryKey: ["products", branchId, "all"], queryFn: () => get<ProductStock[]>("/products", { branch_id: branchId, include_inactive: true }) });
  const ledger = useQuery({ queryKey: ["inv-ledger", branchId], queryFn: () => get<Page<InventoryTxn>>(`/branches/${branchId}/inventory/ledger`, { size: 100 }), enabled: tab === "ledger" });
  const [f, setF] = useState({ product_id: "", quantity: "", kind: "PURCHASE", unit_cost: "", reason: "", reference: "" });
  const m = useMutation({
    mutationFn: () => ["PURCHASE", "OPENING", "RETURN"].includes(f.kind)
      ? post("/inventory/stock-in", { branch_id: branchId, product_id: f.product_id, quantity: f.quantity, txn_type: f.kind, unit_cost: f.unit_cost || undefined, reference: f.reference || undefined })
      : post("/inventory/stock-out", { branch_id: branchId, product_id: f.product_id, quantity: f.quantity, txn_type: f.kind, reason: f.reason }),
    onSuccess: () => { toast("Stock updated (ledger entry created)"); qc.invalidateQueries({ queryKey: ["products"] }); qc.invalidateQueries({ queryKey: ["inv-ledger"] }); setF({ ...f, quantity: "", unit_cost: "", reason: "", reference: "" }); },
  });
  const name = (id: string) => stock.data?.find((s) => s.product.id === id)?.product.name ?? id.slice(0, 8);
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h1 className="text-2xl font-semibold">Inventory</h1><Tabs value={tab} onChange={setTab} items={[{ value: "stock", label: "Stock" }, { value: "ledger", label: "Ledger" }]} /></div>
      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        {tab === "stock" ? (
          <Card className="p-0 sm:p-0">
            <DataTable head={["SKU", "Product", "Price", "Cost", "In stock", ""]}>
              {(stock.data ?? []).map(({ product: p, stock: q }) => (
                <tr key={p.id}><Td className="font-mono text-xs">{p.sku}</Td><Td>{p.name}</Td><Td className="num">{money(p.price)}</Td><Td className="num">{money(p.cost_price)}</Td>
                  <Td className="num">{q === null ? "—" : Number(q)}</Td><Td>{q !== null && num(q) <= p.low_stock_threshold && <Badge tone="red">Low</Badge>}</Td></tr>
              ))}
            </DataTable>
          </Card>
        ) : (
          <Card className="p-0 sm:p-0">
            <DataTable head={["When", "Product", "Type", "Qty", "Balance", "Ref / note"]}>
              {(ledger.data?.items ?? []).map((t) => (
                <tr key={t.id}><Td>{dateTime(t.created_at)}</Td><Td>{name(t.product_id)}</Td><Td><Badge>{t.txn_type}</Badge></Td>
                  <Td className={`num ${num(t.quantity) < 0 ? "text-red-600" : "text-emerald-700"}`}>{num(t.quantity) > 0 ? "+" : ""}{Number(t.quantity)}</Td><Td className="num">{Number(t.balance_after)}</Td><Td className="text-xs">{t.reference ?? t.note}</Td></tr>
              ))}
            </DataTable>
          </Card>
        )}
        <Card className="h-fit">
          <CardTitle>Stock movement</CardTitle>
          <div className="grid gap-3">
            <Field label="Product"><Select value={f.product_id} onChange={(e) => setF({ ...f, product_id: e.target.value })}><option value="">Choose…</option>{(stock.data ?? []).filter((s) => s.product.track_stock).map((s) => <option key={s.product.id} value={s.product.id}>{s.product.name}</option>)}</Select></Field>
            <Field label="Type"><Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
              <option value="PURCHASE">Purchase (receive)</option><option value="OPENING">Opening stock</option><option value="RETURN">Customer return</option>
              <option value="DAMAGED">Damaged</option><option value="SUPPLIER_RETURN">Return to supplier</option><option value="ADJUSTMENT">Count adjustment (±)</option></Select></Field>
            <Field label="Quantity"><Input inputMode="decimal" value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} /></Field>
            {f.kind === "PURCHASE" && <><Field label="Unit cost ₹"><Input inputMode="decimal" value={f.unit_cost} onChange={(e) => setF({ ...f, unit_cost: e.target.value })} /></Field>
              <Field label="Supplier invoice #"><Input value={f.reference} onChange={(e) => setF({ ...f, reference: e.target.value })} /></Field></>}
            {!["PURCHASE", "OPENING", "RETURN"].includes(f.kind) && <Field label="Reason"><Input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></Field>}
          </div>
          <ErrorBox error={m.error} />
          <Button className="mt-4 w-full" disabled={!f.product_id || !f.quantity} loading={m.isPending} onClick={() => m.mutate()}>Save movement</Button>
        </Card>
      </div>
    </div>
  );
}

export function ShiftExpenses() {
  const branchId = useBranchId();
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useAuth();
  const mine = useQuery({ queryKey: ["shift", "me"], queryFn: () => get<{ shift: Shift | null; cash_sales?: string; cash_expenses?: string; expected_cash?: string }>("/shifts/me") });
  const history = useQuery({ queryKey: ["shifts", branchId], queryFn: () => get<Shift[]>(`/branches/${branchId}/shifts`) });
  const cats = useQuery({ queryKey: ["expense-cats"], queryFn: () => get<ExpenseCategory[]>("/expense-categories"), enabled: can("expenses.manage") });
  const day = todayLocal();
  const expenses = useQuery({ queryKey: ["expenses", branchId, day], queryFn: () => get<Expense[]>(`/branches/${branchId}/expenses`, { from: todayLocal(-30), to: day }), enabled: can("expenses.manage") });
  const [cash, setCash] = useState("");
  const [e, setE] = useState({ category_id: "", amount: "", description: "", paid_to: "", method: "CASH" });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["shift"] }); qc.invalidateQueries({ queryKey: ["shifts"] }); qc.invalidateQueries({ queryKey: ["expenses"] }); };
  const open = useMutation({ mutationFn: () => post("/shifts/open", { branch_id: branchId, opening_cash: cash || "0" }), onSuccess: () => { refresh(); setCash(""); toast("Shift opened"); } });
  const close = useMutation({ mutationFn: () => post<Shift>("/shifts/close", { counted_cash: cash || "0" }), onSuccess: (s) => { refresh(); setCash(""); toast(`Shift closed · variance ${money(s.variance)}`, num(s.variance) === 0 ? "ok" : "err"); } });
  const addExp = useMutation({ mutationFn: () => post(`/branches/${branchId}/expenses`, { ...e, category_id: e.category_id || cats.data?.[0]?.id, paid_to: e.paid_to || undefined }), onSuccess: () => { refresh(); setE({ ...e, amount: "", description: "", paid_to: "" }); toast("Expense recorded"); } });
  const s = mine.data?.shift;
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Shift &amp; Expenses</h1>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle>My cash shift</CardTitle>
          {s ? (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Opening cash" value={money(s.opening_cash)} /><Stat label="Cash taken" value={money(mine.data?.cash_sales)} />
                <Stat label="Cash expenses" value={money(mine.data?.cash_expenses)} /><Stat label="Expected in drawer" value={money(mine.data?.expected_cash)} tone="good" />
              </div>
              <Field label="Counted cash ₹"><Input inputMode="decimal" value={cash} onChange={(x) => setCash(x.target.value)} /></Field>
              <Button variant="brass" className="w-full" loading={close.isPending} onClick={() => close.mutate()}>Close shift</Button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-ink-400">Open a shift to track the cash drawer. Cash payments you receive are counted automatically.</p>
              <Field label="Opening cash ₹"><Input inputMode="decimal" value={cash} onChange={(x) => setCash(x.target.value)} /></Field>
              <Button className="w-full" loading={open.isPending} onClick={() => open.mutate()}>Open shift</Button>
            </div>
          )}
          <ErrorBox error={open.error || close.error} />
        </Card>
        {can("expenses.manage") && (
          <Card>
            <CardTitle>Add expense</CardTitle>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Category"><Select value={e.category_id} onChange={(x) => setE({ ...e, category_id: x.target.value })}>{(cats.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
              <Field label="Amount ₹"><Input inputMode="decimal" value={e.amount} onChange={(x) => setE({ ...e, amount: x.target.value })} /></Field>
              <Field label="Description" className="col-span-2"><Input value={e.description} onChange={(x) => setE({ ...e, description: x.target.value })} placeholder="e.g. Cool drinks, electricity bill" /></Field>
              <Field label="Paid to"><Input value={e.paid_to} onChange={(x) => setE({ ...e, paid_to: x.target.value })} /></Field>
              <Field label="Method"><Select value={e.method} onChange={(x) => setE({ ...e, method: x.target.value })}><option>CASH</option><option>UPI</option><option>CARD</option><option>BANK</option></Select></Field>
            </div>
            <ErrorBox error={addExp.error} />
            <Button className="mt-4 w-full" disabled={!num(e.amount) || !e.description} loading={addExp.isPending} onClick={() => addExp.mutate()}>Save expense</Button>
          </Card>
        )}
      </div>
      {can("expenses.manage") && (
        <Card className="p-0 sm:p-0">
          <div className="p-4 pb-0 font-semibold">Expenses (last 30 days)</div>
          <DataTable head={["Date", "Category", "Description", "Paid to", "Method", "Amount"]} empty={expenses.data?.length === 0}>
            {(expenses.data ?? []).map((x) => (
              <tr key={x.id} className={x.is_void ? "line-through opacity-50" : ""}><Td>{x.expense_date}</Td><Td><span style={{ color: x.category.color }}>●</span> {x.category.name}</Td><Td>{x.description}</Td><Td>{x.paid_to}</Td><Td>{x.method}</Td><Td className="num">{money(x.amount)}</Td></tr>
            ))}
          </DataTable>
        </Card>
      )}
      <Card className="p-0 sm:p-0">
        <div className="p-4 pb-0 font-semibold">Shift history</div>
        <DataTable head={["Opened", "Closed", "Opening", "Expected", "Counted", "Variance", "Status"]}>
          {(history.data ?? []).map((h) => (
            <tr key={h.id}><Td>{dateTime(h.opened_at)}</Td><Td>{dateTime(h.closed_at)}</Td><Td className="num">{money(h.opening_cash)}</Td><Td className="num">{money(h.expected_cash)}</Td>
              <Td className="num">{h.counted_cash ? money(h.counted_cash) : "—"}</Td><Td className={`num ${num(h.variance) !== 0 ? "text-red-600" : ""}`}>{h.variance ? money(h.variance) : "—"}</Td><Td><StatusBadge status={h.status} /></Td></tr>
          ))}
        </DataTable>
      </Card>
    </div>
  );
}

export function ApprovalsAlerts() {
  const branchId = useBranchId();
  const { can } = useAuth();
  const qc = useQueryClient();
  const approvals = useQuery({ queryKey: ["approvals", branchId], queryFn: () => get<Approval[]>(`/branches/${branchId}/approvals`) });
  const alerts = useQuery({ queryKey: ["alerts", branchId], queryFn: () => get<Alert[]>(`/branches/${branchId}/alerts`) });
  const resolve = useMutation({ mutationFn: ({ id, approve }: { id: string; approve: boolean }) => post(`/approvals/${id}/resolve`, { approve }), onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }) });
  const ack = useMutation({ mutationFn: (id: string) => post(`/alerts/${id}/ack`), onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }) });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardTitle>Pending approvals</CardTitle>
        {approvals.data?.length ? approvals.data.map((a) => (
          <div key={a.id} className="flex items-center justify-between gap-2 border-b border-line py-3 last:border-0">
            <div className="text-sm"><Badge tone="amber">{a.approval_type.replace("_", " ")}</Badge> <span className="num font-semibold">{a.amount ? money(a.amount) : ""}</span><div className="text-ink-300">{a.reason}</div><div className="text-xs text-ink-400">{dateTime(a.created_at)}</div></div>
            {can("approvals.resolve") && <div className="flex gap-1"><Button size="sm" onClick={() => resolve.mutate({ id: a.id, approve: true })}>Approve</Button><Button size="sm" variant="ghost" onClick={() => resolve.mutate({ id: a.id, approve: false })}>Reject</Button></div>}
          </div>
        )) : <Empty>No pending requests.</Empty>}
        <ErrorBox error={resolve.error} />
      </Card>
      <Card>
        <CardTitle>Open alerts (anti-fraud, devices, stock)</CardTitle>
        {alerts.data?.length ? alerts.data.map((a) => (
          <div key={a.id} className="flex items-start justify-between gap-2 border-b border-line py-3 last:border-0">
            <div className="text-sm"><StatusBadge status={a.severity} /> <span className="font-medium">{a.alert_type.replace(/_/g, " ")}</span><div className="text-ink-300">{a.message}</div><div className="text-xs text-ink-400">{dateTime(a.created_at)}</div></div>
            <Button size="sm" variant="ghost" onClick={() => ack.mutate(a.id)}>Acknowledge</Button>
          </div>
        )) : <Empty>All clear.</Empty>}
      </Card>
    </div>
  );
}
