/** Device registry, live health, detection state per table, event log and simulator. */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/services/api";
import type { DetectionState, Device, DeviceEvent, Table } from "@/types/api";
import { useBranchId } from "@/hooks/useBranch";
import { useAuth } from "@/stores/auth";
import { Badge, Button, Card, CardTitle, DataTable, ErrorBox, Field, Input, Modal, Select, Tabs, Td, useToast } from "@/components/ui";
import { StatusBadge } from "@/components/status";
import { dateTime, time } from "@/lib/format";

const TYPES = ["RFID_READER", "NFC_READER", "MOTION_SENSOR", "PRESSURE_SENSOR", "IR_SENSOR", "VIBRATION_SENSOR", "CAMERA", "TABLE_CONTROLLER", "CUSTOM"];

const OPTIONS = [
  { k: "QR + Manual (MVP)", cost: "₹0", how: "Printed QR on each table; customer scans & taps Start, or staff taps Start on the tablet.", good: "Zero hardware, works today", watch: "Relies on people remembering" },
  { k: "RFID / NFC member card", cost: "₹800–1,500 per table", how: "USB/ESP32 reader at the table; member taps card → session starts with membership minutes.", good: "Identifies the customer, very reliable", watch: "Walk-ins need a counter card" },
  { k: "Table controller / light relay", cost: "₹600–1,200", how: "Start button or smart relay on the table light; light ON only when a session runs.", good: "Enforces billing (no free play in the dark)", watch: "Electrician install" },
  { k: "Physical sensors", cost: "₹300–900 per sensor", how: "PIR motion, IR break-beam at pockets, pressure mat, vibration on rail → ESP32 or Pi gateway.", good: "Automatic, private, cheap", watch: "Never alone — fused with other signals" },
  { k: "Camera + edge AI", cost: "₹3–8k per camera + mini PC", how: "Overhead camera; OpenCV/YOLO on-site computes activity confidence; only metadata leaves the club.", good: "Rich signal, also audits disputes", watch: "Privacy notice, lighting, compute" },
  { k: "Hybrid (recommended long-term)", cost: "Mix of the above", how: "Engine fuses card + sensors + camera; starts only when confidence ≥ threshold for a sustained period.", good: "Highest accuracy, fraud-resistant", watch: "Tune thresholds per club" },
];

export default function Devices() {
  const branchId = useBranchId();
  const { can } = useAuth();
  const [tab, setTab] = useState<"devices" | "detection" | "events" | "options">("devices");
  const devices = useQuery({ queryKey: ["devices", branchId], queryFn: () => get<Device[]>(`/branches/${branchId}/devices`), refetchInterval: 15000 });
  const tables = useQuery({ queryKey: ["tables", branchId], queryFn: () => get<Table[]>(`/branches/${branchId}/tables`) });
  const tname = (id: string | null) => tables.data?.find((t) => t.id === id)?.name ?? "—";
  const [reg, setReg] = useState(false);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Devices &amp; detection</h1>
        <div className="flex gap-2">
          <Tabs value={tab} onChange={setTab} items={[{ value: "devices", label: "Devices" }, { value: "detection", label: "Detection" }, { value: "events", label: "Event log" }, { value: "options", label: "Hardware options" }]} />
          {can("devices.manage") && <Button onClick={() => setReg(true)}>+ Register</Button>}
        </div>
      </div>
      {tab === "devices" && (
        <Card className="p-0 sm:p-0">
          <DataTable head={["Device", "Type", "Table", "Status", "Last seen", "Firmware"]} empty={devices.data?.length === 0}>
            {(devices.data ?? []).map((d) => (
              <tr key={d.id}><Td><div className="font-medium">{d.name}</div><div className="font-mono text-xs text-ink-400">{d.device_id}</div></Td><Td><Badge>{d.device_type}</Badge></Td>
                <Td>{tname(d.table_id)}</Td><Td><StatusBadge status={d.status} /></Td><Td>{dateTime(d.last_seen_at)}</Td><Td className="text-xs">{d.firmware_version ?? "—"}</Td></tr>
            ))}
          </DataTable>
          <p className="p-4 text-xs text-ink-400">If a device is OFFLINE, staff simply use manual Start/Stop on the table — billing never depends on hardware.</p>
        </Card>
      )}
      {tab === "detection" && <Detection tables={tables.data ?? []} />}
      {tab === "events" && <Events tname={tname} />}
      {tab === "options" && (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {OPTIONS.map((o) => (
            <Card key={o.k}><div className="font-semibold text-brass-400">{o.k}</div><div className="text-xs text-ink-400">{o.cost}</div>
              <p className="mt-2 text-sm text-ink-300">{o.how}</p><p className="mt-2 text-xs text-emerald-700">+ {o.good}</p><p className="text-xs text-amber-700">− {o.watch}</p></Card>
          ))}
        </div>
      )}
      {reg && <Register onClose={() => setReg(false)} tables={tables.data ?? []} />}
    </div>
  );
}

function Register({ onClose, tables }: { onClose: () => void; tables: Table[] }) {
  const branchId = useBranchId();
  const qc = useQueryClient();
  const [f, setF] = useState({ device_id: "", name: "", device_type: "MOTION_SENSOR", table_id: "" });
  const m = useMutation({ mutationFn: () => post<{ device: Device; api_key: string }>(`/branches/${branchId}/devices`, { ...f, table_id: f.table_id || null }), onSuccess: () => qc.invalidateQueries({ queryKey: ["devices"] }) });
  return (
    <Modal open onClose={onClose} title="Register device">
      {m.data ? (
        <div className="space-y-3">
          <p className="text-sm">Device <b>{m.data.device.device_id}</b> registered. Copy this key into the gateway/ESP32 config now — it is shown only once.</p>
          <code className="block break-all rounded-lg bg-felt-950 p-3 text-xs text-brass-400">{m.data.api_key}</code>
          <Button className="w-full" onClick={() => navigator.clipboard?.writeText(m.data!.api_key)}>Copy key</Button>
        </div>
      ) : (
        <div className="grid gap-3">
          <Field label="Device ID" hint="e.g. TABLE4_SENSOR"><Input value={f.device_id} onChange={(e) => setF({ ...f, device_id: e.target.value.toUpperCase() })} /></Field>
          <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Type"><Select value={f.device_type} onChange={(e) => setF({ ...f, device_type: e.target.value })}>{TYPES.map((t) => <option key={t}>{t}</option>)}</Select></Field>
          <Field label="Table"><Select value={f.table_id} onChange={(e) => setF({ ...f, table_id: e.target.value })}><option value="">Not assigned</option>{tables.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></Field>
          <ErrorBox error={m.error} />
          <Button loading={m.isPending} disabled={!f.device_id || !f.name} onClick={() => m.mutate()}>Register</Button>
        </div>
      )}
    </Modal>
  );
}

function Detection({ tables }: { tables: Table[] }) {
  const branchId = useBranchId();
  const toast = useToast();
  const st = useQuery({ queryKey: ["detection", branchId], queryFn: () => get<{ health: Record<string, number>; tables: DetectionState[] }>(`/branches/${branchId}/detection-state`), refetchInterval: 5000 });
  const [sim, setSim] = useState({ table_id: "", source: "MOTION", confidence: "0.95", card_uid: "" });
  const m = useMutation({
    mutationFn: () => post<{ outcome: string; reason?: string; score?: number }>("/devices/simulate", { ...sim, table_id: sim.table_id || tables[0]?.id, confidence: Number(sim.confidence), card_uid: sim.card_uid || undefined }),
    onSuccess: (r) => { toast(`${r.outcome}${r.score !== undefined ? ` · score ${r.score}` : ""}${r.reason ? ` · ${r.reason}` : ""}`); st.refetch(); },
  });
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_340px]">
      <Card>
        <CardTitle>Per-table detection state</CardTitle>
        <p className="mb-3 text-xs text-ink-400">IDLE → ACTIVITY_DETECTED → CONFIRMING → GAME_STARTED. Billing starts only after sustained, multi-signal confirmation (or an explicit card/QR/button start).</p>
        <DataTable head={["Table", "State", "Score", "Events", "First / last activity", "Signals"]} empty={st.data?.tables.length === 0}>
          {(st.data?.tables ?? []).map((t) => (
            <tr key={t.table_id}><Td>Table {t.table_number}</Td><Td><Badge tone={t.state === "GAME_STARTED" ? "blue" : t.state === "IDLE" ? "gray" : "amber"}>{t.state}</Badge></Td>
              <Td className="num">{Math.round(t.score * 100)}%</Td><Td>{t.activity_events}</Td><Td className="text-xs">{time(t.first_activity_at)} / {time(t.last_activity_at)}</Td>
              <Td className="text-xs">{t.signals.map((s) => s.source).join(", ")}</Td></tr>
          ))}
        </DataTable>
      </Card>
      <Card className="h-fit">
        <CardTitle>Simulator (commissioning)</CardTitle>
        <div className="grid gap-3">
          <Field label="Table"><Select value={sim.table_id} onChange={(e) => setSim({ ...sim, table_id: e.target.value })}>{tables.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></Field>
          <Field label="Signal"><Select value={sim.source} onChange={(e) => setSim({ ...sim, source: e.target.value })}>{["MOTION", "PRESSURE", "IR", "VIBRATION", "CAMERA", "RFID", "CONTROLLER"].map((s) => <option key={s}>{s}</option>)}</Select></Field>
          <Field label="Confidence"><Input value={sim.confidence} onChange={(e) => setSim({ ...sim, confidence: e.target.value })} /></Field>
          {sim.source === "RFID" && <Field label="Card UID"><Input value={sim.card_uid} onChange={(e) => setSim({ ...sim, card_uid: e.target.value })} /></Field>}
        </div>
        <ErrorBox error={m.error} />
        <Button className="mt-4 w-full" loading={m.isPending} onClick={() => m.mutate()}>Send signal</Button>
        <p className="mt-2 text-xs text-ink-400">Uses the exact same engine as real hardware. Send motion + pressure + camera over ~1 minute to see an automatic HYBRID start.</p>
      </Card>
    </div>
  );
}

function Events({ tname }: { tname: (id: string | null) => string }) {
  const branchId = useBranchId();
  const ev = useQuery({ queryKey: ["device-events", branchId], queryFn: () => get<DeviceEvent[]>(`/branches/${branchId}/device-events`, { limit: 200 }), refetchInterval: 5000 });
  return (
    <Card className="p-0 sm:p-0">
      <DataTable head={["Received", "Table", "Event", "Conf.", "Outcome", "Detail"]} empty={ev.data?.length === 0}>
        {(ev.data ?? []).map((e) => (
          <tr key={e.id}><Td className="text-xs">{dateTime(e.received_at)}</Td><Td>{tname(e.table_id)}</Td><Td>{e.event_type}</Td><Td>{e.confidence ?? "—"}</Td>
            <Td><Badge tone={e.outcome === "SESSION_STARTED" ? "blue" : e.outcome?.startsWith("IGNORED") || e.outcome === "DUPLICATE" ? "gray" : "green"}>{e.outcome}</Badge></Td><Td className="max-w-xs truncate text-xs">{e.detail}</Td></tr>
        ))}
      </DataTable>
    </Card>
  );
}
