/** Live board + table configuration (rates, QR codes) + pricing rules. */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post, put } from "@/services/api";
import type { BoardRow, GameType, PricingRule, Table } from "@/types/api";
import { useBranchId } from "@/hooks/useBranch";
import { useAuth } from "@/stores/auth";
import { Badge, Button, Card, CardTitle, DataTable, ErrorBox, Field, Input, Modal, Select, Spinner, Tabs, Td, useToast } from "@/components/ui";
import { TableBoard } from "@/components/TableBoard";
import { TableStatusBadge } from "@/components/status";
import { money } from "@/lib/format";

export default function Tables() {
  const branchId = useBranchId();
  const { can } = useAuth();
  const [tab, setTab] = useState<"board" | "config" | "pricing">("board");
  const board = useQuery({ queryKey: ["board", branchId], queryFn: () => get<BoardRow[]>(`/branches/${branchId}/board`), enabled: !!branchId, refetchInterval: 30000 });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Tables</h1>
        <Tabs value={tab} onChange={setTab} items={[{ value: "board", label: "Live board" }, ...(can("tables.manage") ? [{ value: "config" as const, label: "Tables & QR" }] : []), ...(can("pricing.manage") ? [{ value: "pricing" as const, label: "Pricing rules" }] : [])]} />
      </div>
      {tab === "board" && (board.data ? <TableBoard rows={board.data} /> : <Spinner />)}
      {tab === "config" && <TableConfig />}
      {tab === "pricing" && <PricingRules />}
    </div>
  );
}

function TableConfig() {
  const branchId = useBranchId();
  const qc = useQueryClient();
  const toast = useToast();
  const [edit, setEdit] = useState<Table | null>(null);
  const [adding, setAdding] = useState(false);
  const tables = useQuery({ queryKey: ["tables", branchId], queryFn: () => get<Table[]>(`/branches/${branchId}/tables`, { include_inactive: true }) });
  const games = useQuery({ queryKey: ["game-types"], queryFn: () => get<GameType[]>("/game-types") });
  const [form, setForm] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { ...form };
      ["hourly_rate", "peak_rate", "off_peak_rate"].forEach((k) => { if (body[k] === "") body[k] = null; });
      ["table_number", "minimum_booking_duration", "maximum_booking_duration"].forEach((k) => { if (body[k] !== undefined) body[k] = Number(body[k]); });
      return edit ? patch(`/tables/${edit.id}`, body) : post(`/branches/${branchId}/tables`, body);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["tables"] }); qc.invalidateQueries({ queryKey: ["board"] }); toast("Saved (price changes are audited)"); setEdit(null); setAdding(false); },
  });
  const open = (t: Table | null) => {
    setEdit(t);
    setAdding(!t);
    setForm(t ? { name: t.name, hourly_rate: t.hourly_rate, peak_rate: t.peak_rate ?? "", off_peak_rate: t.off_peak_rate ?? "", minimum_booking_duration: String(t.minimum_booking_duration), maximum_booking_duration: String(t.maximum_booking_duration), reason: "" }
      : { table_number: "", name: "", game_type_id: games.data?.[0]?.id ?? "", hourly_rate: "", minimum_booking_duration: "30", maximum_booking_duration: "240" });
  };
  const qrUrl = (t: Table) => `${window.location.origin}/t/${t.qr_token}`;
  return (
    <Card>
      <CardTitle action={<Button size="sm" onClick={() => open(null)}>+ Add table</Button>}>Tables</CardTitle>
      <DataTable head={["#", "Name", "Game", "Status", "Rate / Happy / Peak", "QR", ""]}>
        {(tables.data ?? []).map((t) => (
          <tr key={t.id}>
            <Td>{t.table_number}</Td><Td>{t.name}{!t.is_active && <Badge className="ml-2">inactive</Badge>}</Td><Td>{t.game_type.name}</Td>
            <Td><TableStatusBadge status={t.status} /></Td>
            <Td className="num">{money(t.hourly_rate)} / {t.off_peak_rate ? money(t.off_peak_rate) : "—"} / {t.peak_rate ? money(t.peak_rate) : "—"}</Td>
            <Td><a className="text-xs text-brass-400 underline" target="_blank" rel="noreferrer" href={`https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=${encodeURIComponent(qrUrl(t))}`}>Print QR</a></Td>
            <Td><Button size="sm" variant="ghost" onClick={() => open(t)}>Edit</Button></Td>
          </tr>
        ))}
      </DataTable>
      <Modal open={!!edit || adding} onClose={() => { setEdit(null); setAdding(false); }} title={edit ? `Edit ${edit.name}` : "Add table"}>
        <div className="grid gap-3 sm:grid-cols-2">
          {!edit && <Field label="Table number"><Input value={form.table_number ?? ""} onChange={(e) => setForm({ ...form, table_number: e.target.value })} /></Field>}
          <Field label="Name"><Input value={form.name ?? ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          {!edit && (
            <Field label="Game type"><Select value={form.game_type_id} onChange={(e) => setForm({ ...form, game_type_id: e.target.value })}>{(games.data ?? []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</Select></Field>
          )}
          <Field label="Hourly rate ₹"><Input inputMode="decimal" value={form.hourly_rate ?? ""} onChange={(e) => setForm({ ...form, hourly_rate: e.target.value })} /></Field>
          <Field label="Happy-hour / off-peak rate ₹" hint="Used by HAPPY_HOUR / OFF_PEAK rules"><Input inputMode="decimal" value={form.off_peak_rate ?? ""} onChange={(e) => setForm({ ...form, off_peak_rate: e.target.value })} /></Field>
          <Field label="Peak rate ₹" hint="Used by PEAK rules"><Input inputMode="decimal" value={form.peak_rate ?? ""} onChange={(e) => setForm({ ...form, peak_rate: e.target.value })} /></Field>
          <Field label="Min booking (min)"><Input value={form.minimum_booking_duration ?? ""} onChange={(e) => setForm({ ...form, minimum_booking_duration: e.target.value })} /></Field>
          <Field label="Max booking (min)"><Input value={form.maximum_booking_duration ?? ""} onChange={(e) => setForm({ ...form, maximum_booking_duration: e.target.value })} /></Field>
          {edit && <Field label="Reason for change" className="sm:col-span-2"><Input value={form.reason ?? ""} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>}
        </div>
        <ErrorBox error={save.error} />
        <Button className="mt-4 w-full" loading={save.isPending} onClick={() => save.mutate()}>Save</Button>
      </Modal>
    </Card>
  );
}

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function PricingRules() {
  const branchId = useBranchId();
  const qc = useQueryClient();
  const rules = useQuery({ queryKey: ["pricing-rules", branchId], queryFn: () => get<PricingRule[]>(`/branches/${branchId}/pricing-rules`) });
  const games = useQuery({ queryKey: ["game-types"], queryFn: () => get<GameType[]>("/game-types") });
  const blank = { name: "", kind: "STANDARD", day_type: "ANY", start_time: "", end_time: "", customer_segment: "ANY", rate_per_hour: "", rate_multiplier: "", priority: "100", game_type_id: "", valid_from: "", valid_to: "" };
  const [f, setF] = useState<Record<string, string>>(blank);
  const save = useMutation({
    mutationFn: () => {
      const body = {
        ...f, priority: Number(f.priority), start_time: f.start_time || null, end_time: f.end_time || null, game_type_id: f.game_type_id || null,
        rate_per_hour: f.rate_per_hour || null, rate_multiplier: f.rate_multiplier ? Number(f.rate_multiplier) : null, valid_from: f.valid_from || null, valid_to: f.valid_to || null,
      };
      return post(`/branches/${branchId}/pricing-rules`, body);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["pricing-rules"] }); setF(blank); },
  });
  const toggle = useMutation({
    mutationFn: (r: PricingRule) => put(`/branches/${branchId}/pricing-rules/${r.id}`, { ...r, is_active: !r.is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pricing-rules"] }),
  });
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
      <Card>
        <CardTitle>Pricing rules</CardTitle>
        <p className="mb-3 text-xs text-ink-400">Highest priority matching rule wins for each minute. No rule → table base rate. HAPPY_HOUR/OFF_PEAK and PEAK rules use each table's own off-peak / peak rate when set.</p>
        <DataTable head={["Name", "Kind", "When", "Who", "Price", "Priority", ""]}>
          {(rules.data ?? []).map((r) => (
            <tr key={r.id} className={r.is_active ? "" : "opacity-50"}>
              <Td>{r.name}</Td><Td><Badge>{r.kind}</Badge></Td>
              <Td className="text-xs">{r.day_type}{r.days_of_week ? ` (${r.days_of_week.map((d) => DOW[d]).join(",")})` : ""} {r.start_time ? `${r.start_time}–${r.end_time}` : "all day"}{r.valid_from ? ` · ${r.valid_from}→${r.valid_to ?? ""}` : ""}</Td>
              <Td>{r.customer_segment}</Td>
              <Td className="num">{r.rate_per_hour ? `${money(r.rate_per_hour)}/h` : `× ${r.rate_multiplier}`}</Td><Td>{r.priority}</Td>
              <Td><Button size="sm" variant="ghost" onClick={() => toggle.mutate(r)}>{r.is_active ? "Disable" : "Enable"}</Button></Td>
            </tr>
          ))}
        </DataTable>
      </Card>
      <Card>
        <CardTitle>Add rule</CardTitle>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Name" className="col-span-2"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Friday night peak" /></Field>
          <Field label="Kind"><Select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{["STANDARD", "PEAK", "OFF_PEAK", "HAPPY_HOUR", "WEEKEND", "HOLIDAY", "PROMO", "MEMBER"].map((k) => <option key={k}>{k}</option>)}</Select></Field>
          <Field label="Days"><Select value={f.day_type} onChange={(e) => setF({ ...f, day_type: e.target.value })}>{["ANY", "WEEKDAY", "WEEKEND", "HOLIDAY"].map((k) => <option key={k}>{k}</option>)}</Select></Field>
          <Field label="From"><Input type="time" value={f.start_time} onChange={(e) => setF({ ...f, start_time: e.target.value })} /></Field>
          <Field label="To"><Input type="time" value={f.end_time} onChange={(e) => setF({ ...f, end_time: e.target.value })} /></Field>
          <Field label="Customers"><Select value={f.customer_segment} onChange={(e) => setF({ ...f, customer_segment: e.target.value })}>{["ANY", "MEMBER", "NON_MEMBER"].map((k) => <option key={k}>{k}</option>)}</Select></Field>
          <Field label="Game"><Select value={f.game_type_id} onChange={(e) => setF({ ...f, game_type_id: e.target.value })}><option value="">All</option>{(games.data ?? []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</Select></Field>
          <Field label="Rate ₹/h"><Input inputMode="decimal" value={f.rate_per_hour} onChange={(e) => setF({ ...f, rate_per_hour: e.target.value })} /></Field>
          <Field label="or × multiplier"><Input inputMode="decimal" value={f.rate_multiplier} onChange={(e) => setF({ ...f, rate_multiplier: e.target.value })} placeholder="0.8" /></Field>
          <Field label="Valid from"><Input type="date" value={f.valid_from} onChange={(e) => setF({ ...f, valid_from: e.target.value })} /></Field>
          <Field label="Valid to"><Input type="date" value={f.valid_to} onChange={(e) => setF({ ...f, valid_to: e.target.value })} /></Field>
          <Field label="Priority"><Input value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })} /></Field>
        </div>
        <ErrorBox error={save.error} />
        <Button className="mt-4 w-full" loading={save.isPending} disabled={!f.name || (!f.rate_per_hour && !f.rate_multiplier)} onClick={() => save.mutate()}>Save rule</Button>
      </Card>
    </div>
  );
}
