/** Settings · Users & roles · Audit log · Tournaments. */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, patch, post } from "@/services/api";
import type { AuditLog, Customer, GameType, Page, Role, Tournament, TournamentMatch, TournamentPlayer, UserWithRoles } from "@/types/api";
import { useBranchId } from "@/hooks/useBranch";
import { useAuth } from "@/stores/auth";
import { Badge, Button, Card, CardTitle, DataTable, ErrorBox, Field, Input, Modal, Select, Tabs, Td, useToast } from "@/components/ui";
import { StatusBadge } from "@/components/status";
import { dateTime, money } from "@/lib/format";

// ============================================================================ settings
type Settings = Record<"billing" | "booking" | "detection" | "loyalty" | "notifications", Record<string, any>>;
const LABELS: Record<string, string> = {
  interval_minutes: "Billing block (minutes)", rounding: "Rounding", minimum_billable_minutes: "Minimum charge (minutes)", grace_minutes: "Free grace minutes",
  tax_percent: "Tax %", prices_include_tax: "Prices include tax", staff_discount_limit_percent: "Staff discount limit % (above → approval)",
  slot_step_minutes: "Booking slot step", hold_minutes: "Checkout hold (minutes)", min_advance_minutes: "Min advance (minutes)", max_advance_days: "Max advance (days)",
  buffer_minutes: "Cleaning buffer (minutes)", deposit_mode: "Deposit mode", deposit_fixed_amount: "Fixed deposit ₹", deposit_percent: "Deposit %", deposit_minimum: "Minimum deposit ₹",
  free_cancellation_hours: "Free cancellation (hours before)", late_cancellation_refund_percent: "Late cancel refund %", no_show_grace_minutes: "No-show after (minutes)",
  reserve_lead_minutes: "Show RESERVED (minutes before)", allow_early_start_minutes: "Early start allowed (minutes)", allow_reschedule_hours: "Online reschedule until (hours)",
  auto_start_enabled: "Auto-start from sensors/cards", confirmation_threshold: "Confidence threshold (0–1)", min_activity_seconds: "Sustained activity (seconds)",
  min_activity_events: "Min activity events", signal_window_seconds: "Signal window (seconds)", identification_valid_seconds: "Card/QR identification valid (s)",
  require_identification: "Require customer identification", camera_confidence_threshold: "Camera min confidence", rfid_starts_session: "Card tap starts game",
  qr_starts_session: "QR confirm starts game", inactivity_alert_minutes: "Idle alert (minutes)", auto_close_on_inactivity: "Auto-close idle sessions",
  max_session_hours_alert: "Long session alert (hours)", reject_events_older_than_seconds: "Reject events older than (s)", clock_skew_tolerance_seconds: "Clock skew tolerance (s)",
  enabled: "Enabled", spend_per_point: "₹ spent per point", point_value: "₹ value per point", referral_bonus_points: "Referral bonus points", min_redeem_points: "Min redeem points",
  booking_reminder_minutes: "Booking reminder (minutes before)", session_ending_reminder_minutes: "Session ending reminder (minutes)", membership_expiry_days: "Membership expiry notice (days)",
};

export function Settings() {
  const branchId = useBranchId();
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState<keyof Settings>("billing");
  const s = useQuery({ queryKey: ["settings", branchId], queryFn: () => get<Settings>(`/branches/${branchId}/settings`) });
  const [draft, setDraft] = useState<Record<string, any>>({});
  const save = useMutation({ mutationFn: () => patch<Settings>(`/branches/${branchId}/settings`, { [tab]: draft }), onSuccess: () => { toast("Settings saved (audited)"); setDraft({}); qc.invalidateQueries({ queryKey: ["settings"] }); } });
  const section = s.data?.[tab] ?? {};
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Settings</h1>
        <Tabs value={tab} onChange={(v) => { setTab(v); setDraft({}); }} items={[{ value: "billing", label: "Billing" }, { value: "booking", label: "Booking & deposit" }, { value: "detection", label: "Auto detection" }, { value: "loyalty", label: "Loyalty" }, { value: "notifications", label: "Notifications" }]} />
      </div>
      <Card>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(section).filter(([k]) => k !== "weights" && k !== "channels").map(([k, v]) => {
            const val = k in draft ? draft[k] : v;
            return (
              <Field key={k} label={LABELS[k] ?? k}>
                {typeof v === "boolean" ? (
                  <Select value={String(val)} onChange={(e) => setDraft({ ...draft, [k]: e.target.value === "true" })}><option value="true">Yes</option><option value="false">No</option></Select>
                ) : k === "rounding" ? (
                  <Select value={val} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}><option>UP</option><option>NEAREST</option><option>DOWN</option></Select>
                ) : k === "deposit_mode" ? (
                  <Select value={val} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}><option>FIXED</option><option>PERCENT</option></Select>
                ) : k === "interval_minutes" ? (
                  <Select value={val} onChange={(e) => setDraft({ ...draft, [k]: Number(e.target.value) })}>{[1, 5, 10, 15, 30, 60].map((m) => <option key={m} value={m}>{m}</option>)}</Select>
                ) : (
                  <Input value={String(val)} onChange={(e) => setDraft({ ...draft, [k]: typeof v === "number" ? Number(e.target.value) : e.target.value })} />
                )}
              </Field>
            );
          })}
        </div>
        {tab === "detection" && section.weights && (
          <p className="mt-4 text-xs text-ink-400">Signal weights: {Object.entries(section.weights).map(([k, w]) => `${k} ${w}`).join(" · ")}. Fused score = 1 − Π(1 − weight × confidence) across different sources.</p>
        )}
        <ErrorBox error={save.error} />
        <Button className="mt-4" disabled={!Object.keys(draft).length} loading={save.isPending} onClick={() => save.mutate()}>Save changes</Button>
      </Card>
    </div>
  );
}

// ============================================================================ users
export function Users() {
  const { branch } = useAuth();
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => get<UserWithRoles[]>("/users") });
  const roles = useQuery({ queryKey: ["roles"], queryFn: () => get<Role[]>("/roles") });
  const [f, setF] = useState({ username: "", full_name: "", password: "", pin: "", role: "STAFF" });
  const [adding, setAdding] = useState(false);
  const create = useMutation({
    mutationFn: () => post("/users", { username: f.username, full_name: f.full_name, password: f.password || undefined, pin: f.pin || undefined, roles: [{ role_code: f.role, branch_id: f.role === "SUPER_ADMIN" ? null : branch?.id }] }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); setAdding(false); },
  });
  const toggle = useMutation({ mutationFn: (u: UserWithRoles) => patch(`/users/${u.id}`, { is_active: !u.is_active }), onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }) });
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between"><h1 className="text-2xl font-semibold">Users &amp; roles</h1><Button onClick={() => setAdding(true)}>+ Add staff</Button></div>
      <Card className="p-0 sm:p-0">
        <DataTable head={["Name", "Username", "Roles", "Last login", "Status", ""]}>
          {(users.data ?? []).map((u) => (
            <tr key={u.id}><Td>{u.full_name}</Td><Td className="font-mono text-xs">{u.username}</Td><Td>{u.roles.map((r) => <Badge key={r.code + r.branch_id} className="mr-1">{r.name}</Badge>)}</Td>
              <Td>{dateTime(u.last_login_at)}</Td><Td><StatusBadge status={u.is_active ? "ACTIVE" : "SUSPENDED"} /></Td>
              <Td><Button size="sm" variant="ghost" onClick={() => toggle.mutate(u)}>{u.is_active ? "Disable" : "Enable"}</Button></Td></tr>
          ))}
        </DataTable>
      </Card>
      <Card>
        <CardTitle>Roles &amp; permissions</CardTitle>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(roles.data ?? []).map((r) => (
            <div key={r.id} className="rounded-xl border border-line p-3"><div className="font-medium">{r.name}</div>
              <div className="mt-1 flex flex-wrap gap-1">{r.permissions.map((p) => <span key={p.code} title={p.description} className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] text-ink-300">{p.code}</span>)}</div></div>
          ))}
        </div>
      </Card>
      <Modal open={adding} onClose={() => setAdding(false)} title="Add staff member">
        <div className="grid gap-3">
          <Field label="Full name"><Input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
          <Field label="Username"><Input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value.toLowerCase() })} /></Field>
          <Field label="Password (min 8)"><Input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
          <Field label="Counter PIN (4–8 digits)"><Input inputMode="numeric" value={f.pin} onChange={(e) => setF({ ...f, pin: e.target.value })} /></Field>
          <Field label="Role"><Select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{(roles.data ?? []).filter((r) => r.code !== "CUSTOMER").map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}</Select></Field>
        </div>
        <ErrorBox error={create.error} />
        <Button className="mt-4 w-full" loading={create.isPending} onClick={() => create.mutate()}>Create user</Button>
      </Modal>
    </div>
  );
}

// ============================================================================ audit
export function Audit() {
  const branchId = useBranchId();
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);
  const q = useQuery({ queryKey: ["audit", branchId, action, page], queryFn: () => get<Page<AuditLog>>("/audit-logs", { branch_id: branchId, action: action || undefined, page, size: 50 }) });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold">Audit log</h1>
        <Field label="Action starts with"><Select value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }}>
          <option value="">All</option>{["auth", "booking", "session", "invoice", "payment", "table", "pricing_rule", "inventory", "membership", "user", "device", "branch", "approval", "shift", "expense"].map((a) => <option key={a}>{a}</option>)}
        </Select></Field>
      </div>
      <Card className="p-0 sm:p-0">
        <DataTable head={["When", "User", "Action", "Entity", "Before → After", "Reason", "IP"]}>
          {(q.data?.items ?? []).map((a) => (
            <tr key={a.id}><Td className="whitespace-nowrap text-xs">{dateTime(a.created_at)}</Td><Td>{a.username}</Td><Td><Badge>{a.action}</Badge></Td><Td className="text-xs">{a.entity_type}</Td>
              <Td className="max-w-md text-xs"><code className="break-all text-ink-300">{a.before ? JSON.stringify(a.before) : ""}{a.before && a.after ? " → " : ""}{a.after ? JSON.stringify(a.after) : ""}</code></Td>
              <Td className="text-xs">{a.reason}</Td><Td className="text-xs">{a.ip}</Td></tr>
          ))}
        </DataTable>
        <div className="flex justify-between p-3 text-sm"><Button size="sm" variant="ghost" disabled={page === 1} onClick={() => setPage(page - 1)}>← Newer</Button><span className="text-ink-400">{q.data?.total ?? 0} entries</span><Button size="sm" variant="ghost" disabled={(q.data?.items.length ?? 0) < 50} onClick={() => setPage(page + 1)}>Older →</Button></div>
      </Card>
    </div>
  );
}

// ============================================================================ tournaments
export function Tournaments() {
  const branchId = useBranchId();
  const qc = useQueryClient();
  const toast = useToast();
  const list = useQuery({ queryKey: ["tournaments", branchId], queryFn: () => get<Tournament[]>(`/branches/${branchId}/tournaments`) });
  const games = useQuery({ queryKey: ["game-types"], queryFn: () => get<GameType[]>("/game-types") });
  const [sel, setSel] = useState<string | null>(null);
  const [f, setF] = useState({ name: "", format: "KNOCKOUT", entry_fee: "0", game_type_id: "", starts_on: "" });
  const create = useMutation({ mutationFn: () => post<Tournament>(`/branches/${branchId}/tournaments`, { ...f, game_type_id: f.game_type_id || games.data?.[0]?.id, starts_on: f.starts_on || null }), onSuccess: (t) => { qc.invalidateQueries({ queryKey: ["tournaments"] }); setSel(t.id); toast("Tournament created"); } });
  return (
    <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold">Tournaments</h1>
        <Card>
          <CardTitle>New tournament</CardTitle>
          <div className="grid gap-3">
            <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Game"><Select value={f.game_type_id} onChange={(e) => setF({ ...f, game_type_id: e.target.value })}>{(games.data ?? []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</Select></Field>
            <Field label="Format"><Select value={f.format} onChange={(e) => setF({ ...f, format: e.target.value })}><option>KNOCKOUT</option><option>ROUND_ROBIN</option><option>GROUPS_KNOCKOUT</option></Select></Field>
            <Field label="Entry fee ₹"><Input value={f.entry_fee} onChange={(e) => setF({ ...f, entry_fee: e.target.value })} /></Field>
            <Field label="Starts on"><Input type="date" value={f.starts_on} onChange={(e) => setF({ ...f, starts_on: e.target.value })} /></Field>
          </div>
          <ErrorBox error={create.error} />
          <Button className="mt-3 w-full" disabled={!f.name} loading={create.isPending} onClick={() => create.mutate()}>Create</Button>
        </Card>
        {(list.data ?? []).map((t) => (
          <button key={t.id} onClick={() => setSel(t.id)} className={`block w-full rounded-xl border p-3 text-left ${sel === t.id ? "border-brass-400" : "border-line"}`}>
            <div className="font-medium">{t.name}</div><div className="text-xs text-ink-400">{t.format} · {money(t.entry_fee)} · <StatusBadge status={t.status} /></div>
          </button>
        ))}
      </div>
      {sel && <TournamentDetail id={sel} />}
    </div>
  );
}

function TournamentDetail({ id }: { id: string }) {
  const qc = useQueryClient();
  const d = useQuery({ queryKey: ["tournament", id], queryFn: () => get<{ tournament: Tournament; players: TournamentPlayer[]; matches: TournamentMatch[]; leaderboard: any[] }>(`/tournaments/${id}`) });
  const [q, setQ] = useState("");
  const found = useQuery({ queryKey: ["customers", q], queryFn: () => get<Page<Customer>>("/customers", { q, size: 6 }), enabled: q.length >= 2 });
  const refresh = () => qc.invalidateQueries({ queryKey: ["tournament", id] });
  const add = useMutation({ mutationFn: (cid: string) => post(`/tournaments/${id}/players`, { customer_id: cid, fee_paid: true }), onSuccess: refresh });
  const start = useMutation({ mutationFn: () => post(`/tournaments/${id}/start`), onSuccess: refresh });
  const result = useMutation({ mutationFn: ({ mid, s1, s2 }: { mid: string; s1: number; s2: number }) => post(`/tournament-matches/${mid}/result`, { score1: s1, score2: s2 }), onSuccess: refresh });
  if (!d.data) return null;
  const { tournament: t, players, matches, leaderboard } = d.data;
  const pname = (pid: string | null) => players.find((p) => p.id === pid)?.display_name ?? (pid ? "?" : "TBD / bye");
  const rounds = [...new Set(matches.map((m) => `${m.stage}-${m.round_no}`))];
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><div className="text-xl font-semibold">{t.name}</div><div className="text-sm text-ink-400">{t.format} · {players.length} players · <StatusBadge status={t.status} /></div></div>
        {t.status === "REGISTRATION" && <Button loading={start.isPending} disabled={players.length < 2} onClick={() => start.mutate()}>Generate draw &amp; start</Button>}
        {t.winner_player_id && <Badge tone="amber">🏆 {pname(t.winner_player_id)}</Badge>}
      </div>
      <ErrorBox error={start.error || add.error || result.error} />
      {t.status === "REGISTRATION" && (
        <div>
          <Input placeholder="Add player: search customer" value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="mt-2 flex flex-wrap gap-1">{(found.data?.items ?? []).map((c) => <Button key={c.id} size="sm" variant="secondary" onClick={() => add.mutate(c.id)}>+ {c.name}</Button>)}</div>
          <div className="mt-3 flex flex-wrap gap-1">{players.map((p) => <Badge key={p.id}>{p.display_name}</Badge>)}</div>
        </div>
      )}
      {rounds.map((r) => (
        <div key={r}>
          <div className="mb-2 text-xs uppercase tracking-wide text-ink-400">{r.replace("-", " round ")}</div>
          <div className="grid gap-2 md:grid-cols-2">
            {matches.filter((m) => `${m.stage}-${m.round_no}` === r).map((m) => <MatchCard key={m.id} m={m} pname={pname} onResult={(s1, s2) => result.mutate({ mid: m.id, s1, s2 })} />)}
          </div>
        </div>
      ))}
      {leaderboard.length > 0 && t.format !== "KNOCKOUT" && (
        <DataTable head={["#", "Player", "W", "L", "Frames", "Pts"]}>{leaderboard.map((l, i) => <tr key={l.player_id}><Td>{i + 1}</Td><Td>{l.name}</Td><Td>{l.wins}</Td><Td>{l.losses}</Td><Td>{l.frames_for}-{l.frames_against}</Td><Td>{l.points}</Td></tr>)}</DataTable>
      )}
    </Card>
  );
}

function MatchCard({ m, pname, onResult }: { m: TournamentMatch; pname: (id: string | null) => string; onResult: (a: number, b: number) => void }) {
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const playable = m.status === "SCHEDULED" && m.player1_id && m.player2_id;
  return (
    <div className="rounded-xl border border-line p-3 text-sm">
      <div className={`flex justify-between ${m.winner_id === m.player1_id && m.winner_id ? "font-semibold text-emerald-700" : ""}`}><span>{pname(m.player1_id)}</span><span>{m.score1 ?? ""}</span></div>
      <div className={`flex justify-between ${m.winner_id === m.player2_id && m.winner_id ? "font-semibold text-emerald-700" : ""}`}><span>{pname(m.player2_id)}</span><span>{m.score2 ?? ""}</span></div>
      {playable && (
        <div className="mt-2 flex gap-1">
          <Input className="h-8" aria-label="Score 1" value={a} onChange={(e) => setA(e.target.value)} /><Input className="h-8" aria-label="Score 2" value={b} onChange={(e) => setB(e.target.value)} />
          <Button size="sm" disabled={a === "" || b === ""} onClick={() => onResult(Number(a), Number(b))}>Save</Button>
        </div>
      )}
    </div>
  );
}
