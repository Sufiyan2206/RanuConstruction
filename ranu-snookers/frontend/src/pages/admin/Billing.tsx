import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/services/api";
import type { Invoice, Page, ProductStock } from "@/types/api";
import { useBranchId } from "@/hooks/useBranch";
import { Button, Card, CardTitle, DataTable, ErrorBox, Modal, Select, Tabs, Td } from "@/components/ui";
import { StatusBadge } from "@/components/status";
import { InvoicePanel } from "@/components/InvoicePanel";
import { CustomerPicker, type PickedCustomer } from "@/components/CustomerPicker";
import { dateTime, money } from "@/lib/format";
import { useAuth } from "@/stores/auth";

export default function Billing() {
  const branchId = useBranchId();
  const [status, setStatus] = useState("ISSUED,PARTIALLY_PAID");
  const [open, setOpen] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["invoices", branchId, status], queryFn: () => get<Page<Invoice>>(`/branches/${branchId}/invoices`, { status, size: 100 }), enabled: !!branchId });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Billing</h1>
        <Select className="max-w-56" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter">
          <option value="ISSUED,PARTIALLY_PAID">Unpaid</option><option value="PAID">Paid</option><option value="VOID">Void</option><option value="">All</option>
        </Select>
      </div>
      <Card className="p-0 sm:p-0">
        <DataTable head={["Bill", "Issued", "Customer", "Total", "Balance", "Status"]} empty={q.data?.items.length === 0}>
          {(q.data?.items ?? []).map((i) => (
            <tr key={i.id} className="cursor-pointer hover:bg-surface-2" onClick={() => setOpen(i.id)}>
              <Td className="font-mono text-xs">{i.number}</Td><Td>{dateTime(i.issued_at)}</Td><Td>{i.customer_name ?? "Walk-in"}</Td>
              <Td className="num">{money(i.total)}</Td><Td className="num font-semibold">{money(i.balance_due)}</Td><Td><StatusBadge status={i.status} /></Td>
            </tr>
          ))}
        </DataTable>
      </Card>
      {open && <Modal open onClose={() => setOpen(null)} title="Bill"><InvoiceActions id={open} onClose={() => setOpen(null)} /></Modal>}
    </div>
  );
}

function InvoiceActions({ id, onClose }: { id: string; onClose: () => void }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const voidM = useMutation({ mutationFn: (reason: string) => post(`/invoices/${id}/void`, { reason }), onSuccess: () => { qc.invalidateQueries({ queryKey: ["invoices"] }); onClose(); } });
  return (
    <div className="space-y-4">
      <InvoicePanel invoiceId={id} onDone={() => qc.invalidateQueries({ queryKey: ["invoices"] })} />
      {can("billing.adjust") && (
        <details className="text-sm"><summary className="cursor-pointer text-ink-400">Void unpaid bill…</summary>
          <p className="my-2 text-xs text-ink-400">Reverses membership minutes and stock. Paid bills must be refunded instead.</p>
          <Button variant="danger" size="sm" onClick={() => { const r = prompt("Reason for voiding?"); if (r && r.length >= 3) voidM.mutate(r); }}>Void bill</Button>
          <ErrorBox error={voidM.error} />
        </details>
      )}
    </div>
  );
}

/** Counter sale (no table): pick products → bill → pay. */
export function Pos() {
  const { branch } = useAuth();
  const [cart, setCart] = useState<Record<string, number>>({});
  const [customer, setCustomer] = useState<PickedCustomer | null>(null);
  const [cat, setCat] = useState("all");
  const [invoice, setInvoice] = useState<string | null>(null);
  const products = useQuery({ queryKey: ["products", branch?.id], queryFn: () => get<ProductStock[]>("/products", { branch_id: branch?.id }), enabled: !!branch });
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => get<{ id: string; name: string }[]>("/product-categories") });
  const sale = useMutation({
    mutationFn: async () => {
      let customerId = customer?.id;
      if (customer && !customerId) customerId = (await post<{ id: string }>("/customers", { name: customer.name, phone: customer.phone })).id;
      return post<Invoice>("/pos/sales", { branch_id: branch!.id, customer_id: customerId, items: Object.entries(cart).filter(([, q]) => q > 0).map(([product_id, quantity]) => ({ product_id, quantity })) });
    },
    onSuccess: (inv) => { setInvoice(inv.id); setCart({}); products.refetch(); },
  });
  const list = (products.data ?? []).filter((p) => cat === "all" || p.product.category_id === cat);
  const lines = (products.data ?? []).filter((p) => cart[p.product.id]);
  const total = lines.reduce((s, p) => s + cart[p.product.id] * Number(p.product.price), 0);
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
      <div className="space-y-3">
        <h1 className="text-2xl font-semibold">POS · Counter sale</h1>
        <Tabs value={cat} onChange={setCat} items={[{ value: "all", label: "All" }, ...(categories.data ?? []).map((c) => ({ value: c.id, label: c.name }))]} />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
          {list.map(({ product: p, stock }) => (
            <button key={p.id} disabled={stock !== null && Number(stock) <= (cart[p.id] ?? 0)} onClick={() => setCart({ ...cart, [p.id]: (cart[p.id] ?? 0) + 1 })}
              className="rounded-2xl border border-line bg-surface p-3 text-left hover:border-brass-500 disabled:opacity-40">
              <div className="font-medium">{p.name}</div>
              <div className="num text-brass-400">{money(p.price)}</div>
              <div className="text-xs text-ink-400">{stock !== null ? `${Number(stock)} in stock` : "made to order"}</div>
            </button>
          ))}
        </div>
      </div>
      <Card className="h-fit lg:sticky lg:top-20">
        <CardTitle>Cart</CardTitle>
        {lines.map(({ product: p }) => (
          <div key={p.id} className="flex items-center justify-between py-1 text-sm">
            <span>{p.name}</span>
            <span className="flex items-center gap-2">
              <Button size="sm" variant="ghost" aria-label="Remove one" onClick={() => setCart({ ...cart, [p.id]: cart[p.id] - 1 })}>−</Button>
              <span className="num">{cart[p.id]}</span>
              <span className="num w-16 text-right">{money(cart[p.id] * Number(p.price))}</span>
            </span>
          </div>
        ))}
        <div className="my-3"><CustomerPicker value={customer} onChange={setCustomer} /></div>
        <div className="num mb-3 flex justify-between text-lg font-semibold"><span>Total</span><span>{money(total)}</span></div>
        <ErrorBox error={sale.error} />
        <Button size="lg" className="w-full" disabled={!total} loading={sale.isPending} onClick={() => sale.mutate()}>Create bill</Button>
      </Card>
      {invoice && <Modal open onClose={() => setInvoice(null)} title="Counter sale"><InvoicePanel invoiceId={invoice} onDone={() => setInvoice(null)} /></Modal>}
    </div>
  );
}
