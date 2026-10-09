/** Search a registered customer by name/phone, or quick-create a new one. */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { get } from "@/services/api";
import type { Customer, Page } from "@/types/api";
import { Button, Input } from "@/components/ui";

export interface PickedCustomer { id?: string; name: string; phone: string }

export function CustomerPicker({ value, onChange }: { value: PickedCustomer | null; onChange: (c: PickedCustomer | null) => void }) {
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const { data } = useQuery({ queryKey: ["customers", q], queryFn: () => get<Page<Customer>>("/customers", { q, size: 8 }), enabled: q.trim().length >= 2 });

  if (value) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-brass-500/50 bg-brass-50 px-3 py-2">
        <div>
          <div className="font-medium">{value.name}</div>
          <div className="text-xs text-ink-400">{value.phone}{value.id ? "" : " · new"}</div>
        </div>
        <Button size="sm" variant="ghost" onClick={() => onChange(null)}>Change</Button>
      </div>
    );
  }
  if (creating) {
    return (
      <div className="space-y-2">
        <Input placeholder="Customer name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Customer name" />
        <Input placeholder="Mobile (WhatsApp)" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} aria-label="Customer mobile" />
        <div className="flex gap-2">
          <Button size="sm" disabled={!name || phone.replace(/\D/g, "").length < 10} onClick={() => onChange({ name, phone })}>Use new customer</Button>
          <Button size="sm" variant="ghost" onClick={() => setCreating(false)}>Search instead</Button>
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-2">
      <Input placeholder="Search name or phone…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search customer" />
      {data && data.items.length > 0 && (
        <ul className="max-h-48 overflow-y-auto rounded-lg border border-line">
          {data.items.map((c) => (
            <li key={c.id}>
              <button className="flex w-full justify-between px-3 py-2 text-left text-sm hover:bg-surface-2" onClick={() => onChange({ id: c.id, name: c.name, phone: c.phone })}>
                <span>{c.name}</span><span className="text-ink-400">{c.phone}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <Button size="sm" variant="outline" onClick={() => { setCreating(true); setPhone(/^\d+$/.test(q) ? q : ""); setName(/^\d+$/.test(q) ? "" : q); }}>+ New customer</Button>
    </div>
  );
}
