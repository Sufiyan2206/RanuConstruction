/** Booking wizard: branch → game → date → time → duration → table → details → deposit → confirmation. */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { get } from "@/services/api";
import { createHold, customerSchema, fetchAvailability, fetchTimeline, type CustomerForm } from "@/services/booking";
import type { Availability, GameType } from "@/types/api";
import { useAuth } from "@/stores/auth";
import { useRealtime } from "@/hooks/useRealtime";
import { Badge, Button, ErrorBox, Field, Input, Select, Spinner } from "@/components/ui";
import { cn } from "@/lib/cn";
import { TableArt, tableImage } from "@/components/TableArt";
import { Table3D } from "@/components/Table3D";
import { Reveal, TiltGlare, useTilt } from "@/components/Motion";
import { localToIso, minutesLabel, money, time, todayLocal } from "@/lib/format";

const DURATIONS = [30, 60, 90, 120, 180];

function timeSlots(open: string, close: string, step = 30): string[] {
  const [oh, om] = open.split(":").map(Number);
  const [ch, cm] = close.split(":").map(Number);
  let end = ch * 60 + cm;
  const start = oh * 60 + om;
  if (end <= start) end += 24 * 60;
  const out: string[] = [];
  for (let t = start; t < end; t += step) out.push(`${String(Math.floor(t / 60) % 24).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`);
  return out;
}

function TableChoice({ a, selected: sel, onPick }: { a: Availability; selected: boolean; onPick: () => void }) {
  const ok = a.status === "AVAILABLE";
  const tilt = useTilt<HTMLButtonElement>();
  return (
    <button ref={tilt.ref} onPointerMove={ok ? tilt.onPointerMove : undefined} onPointerLeave={tilt.onPointerLeave} disabled={!ok} onClick={onPick} aria-pressed={sel}
      className={cn("group relative w-full overflow-hidden rounded-2xl border bg-white text-left shadow-[var(--shadow-card)]", ok && tilt.className,
        ok ? "border-line hover:shadow-[var(--shadow-lift)]" : "cursor-not-allowed border-line opacity-70 grayscale-[60%]",
        sel && "border-brass-500 ring-4 ring-brass-500/20")}>
      <TableArt src={tableImage(a.table)} className="aspect-[16/9]">
        <div className="flex h-full flex-col justify-between p-3">
          <div className="flex items-start justify-between">
            {sel ? <span className="rounded-full bg-brass-500 px-2.5 py-0.5 text-[11px] font-bold text-felt-950 shadow">✓ Selected</span> : <span />}
            <Badge tone={ok ? "green" : a.status === "MAINTENANCE" ? "gray" : "red"} className="bg-white/95 shadow-sm">{ok ? "Available" : a.status === "IN_USE" ? "In use" : a.status === "BOOKED" ? "Booked" : a.status.toLowerCase()}</Badge>
          </div>
          <div>
            <div className="font-display text-2xl font-semibold text-white drop-shadow">{a.table.name}</div>
            <div className="text-xs font-medium uppercase tracking-[0.14em] text-white/80">{a.table.game_type.name}</div>
          </div>
        </div>
      </TableArt>
      <div className="p-4">
        {ok && a.quote ? (
          <div className="flex items-end justify-between gap-3">
            <div>
              <div className="num font-display text-3xl font-semibold text-ink-50">{money(a.quote.amount)}</div>
              <div className="text-xs text-ink-400">Deposit now <span className="font-semibold text-brass-400">{money(a.quote.deposit)}</span> · rest at the club</div>
              {a.quote.segments.length > 1 && <div className="mt-1 text-xs text-emerald-700">{a.quote.segments.map((s) => `${s.minutes}m ${s.rule}`).join(" + ")}</div>}
            </div>
            <span className={cn("shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold transition", sel ? "bg-brass-500 text-felt-950" : "border border-line text-ink-300 group-hover:border-brass-500 group-hover:text-brass-600")}>{sel ? "Selected" : "Select"}</span>
          </div>
        ) : (
          <div className="text-sm text-ink-300">{a.next_available_at ? <>Next free at <b className="text-ink-50">{time(a.next_available_at)}</b></> : a.reason ?? "Not available"}</div>
        )}
      </div>
      <TiltGlare />
    </button>
  );
}

export default function Book() {
  const { branch, branches, setBranch, me } = useAuth();
  const nav = useNavigate();
  useRealtime(branch?.id, "public");
  const [game, setGame] = useState<string>("");
  const [day, setDay] = useState(todayLocal());
  const [slot, setSlot] = useState("18:00");
  const [duration, setDuration] = useState(60);
  const [picked, setPicked] = useState<Availability | null>(null);

  const games = useQuery({ queryKey: ["public-games"], queryFn: () => get<GameType[]>("/public/game-types") });
  const slots = useMemo(() => (branch ? timeSlots(branch.opening_time, branch.closing_time) : []), [branch]);
  // After-midnight slots belong to the same business day but the next calendar date.
  const startIso = useMemo(() => {
    if (!branch) return "";
    const afterMidnight = slot < branch.opening_time;
    const d = afterMidnight ? new Date(new Date(`${day}T00:00:00+05:30`).getTime() + 86400000) : new Date(`${day}T00:00:00+05:30`);
    const localDay = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(d);
    return localToIso(localDay, slot);
  }, [branch, day, slot]);

  const avail = useQuery({
    queryKey: ["availability", branch?.id, startIso, duration, game],
    queryFn: () => fetchAvailability(branch!.id, startIso, duration, game || undefined),
    enabled: !!branch && !!startIso, retry: false,
  });
  const timeline = useQuery({ queryKey: ["timeline", branch?.id, day, game], queryFn: () => fetchTimeline(branch!.id, day, game || undefined), enabled: !!branch });

  const form = useForm<CustomerForm>({ resolver: zodResolver(customerSchema), defaultValues: { name: me?.user.full_name ?? "", phone: me?.user.phone ?? "", email: me?.user.email ?? "" } });
  const hold = useMutation({
    mutationFn: (c: CustomerForm) => createHold({ branch_id: branch!.id, table_id: picked!.table.id, start_at: startIso, duration_minutes: duration, customer: { name: c.name, phone: c.phone, email: c.email || undefined } }),
    onSuccess: (r) => nav(`/booking/${r.booking.reference}`, { state: r }),
  });

  if (!branch) return <div className="grid place-items-center p-20"><Spinner /></div>;

  return (
    <div className="mx-auto max-w-6xl px-4 pb-10">
      <section className="relative -mx-4 mb-8 grid items-center gap-2 px-4 pt-8 lg:grid-cols-[0.9fr_1.1fr] lg:pt-4">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-full bg-[radial-gradient(700px_380px_at_75%_30%,rgba(201,162,75,0.16),transparent_70%)]" />
        <div className="relative z-10 space-y-5 py-6">
          <div className="eyebrow fade-up">Reserve your table</div>
          <h1 className="fade-up font-display text-5xl font-semibold leading-[1.02] tracking-tight [animation-delay:150ms] sm:text-6xl">
            Line up<br />the <span className="text-gold-gradient italic">perfect break.</span>
          </h1>
          <p className="fade-up max-w-md text-lg leading-relaxed text-ink-300 [animation-delay:300ms]">Live prices and availability. Pick a time, choose your table, and it’s held for 10 minutes while you pay a small deposit.</p>
          <div className="fade-up flex flex-wrap gap-6 text-sm [animation-delay:450ms]">
            {["Tournament-grade cloth", "Pay the rest at the club", "Instant WhatsApp confirmation"].map((t) => (
              <span key={t} className="flex items-center gap-2 text-ink-300"><span className="grid size-5 place-items-center rounded-full bg-brass-100 text-[10px] text-brass-600">✓</span>{t}</span>
            ))}
          </div>
        </div>
        <Table3D className="fade-up -mt-6 h-[300px] [animation-delay:200ms] [animation-duration:2.2s] sm:h-[400px] lg:h-[460px]" />
      </section>

      <div className="relative z-10 grid gap-4 rounded-2xl border border-line bg-white/95 p-5 shadow-[var(--shadow-lift)] backdrop-blur sm:grid-cols-2 lg:grid-cols-5">
        {branches.length > 1 && (
          <Field label="Branch">
            <Select value={branch.id} onChange={(e) => { const b = branches.find((x) => x.id === e.target.value); if (b) setBranch(b); setPicked(null); }}>
              {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          </Field>
        )}
        <Field label="Game">
          <Select value={game} onChange={(e) => { setGame(e.target.value); setPicked(null); }}>
            <option value="">All games</option>
            {(games.data ?? []).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
          </Select>
        </Field>
        <Field label="Date"><Input type="date" min={todayLocal()} max={todayLocal(30)} value={day} onChange={(e) => { setDay(e.target.value); setPicked(null); }} /></Field>
        <Field label="Start time">
          <Select value={slot} onChange={(e) => { setSlot(e.target.value); setPicked(null); }}>
            {slots.map((s) => <option key={s} value={s}>{new Date(`2000-01-01T${s}:00`).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}</option>)}
          </Select>
        </Field>
        <Field label="Duration">
          <Select value={duration} onChange={(e) => { setDuration(Number(e.target.value)); setPicked(null); }}>
            {DURATIONS.map((d) => <option key={d} value={d}>{minutesLabel(d)}</option>)}
          </Select>
        </Field>
      </div>

      <h2 className="font-display mb-4 mt-10 text-2xl font-semibold">Available tables <span className="font-sans text-base font-normal text-ink-400">· {time(startIso)}–{time(new Date(new Date(startIso).getTime() + duration * 60000).toISOString())}</span></h2>
      {avail.isLoading && <Spinner />}
      <ErrorBox error={avail.error} />
      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {(avail.data ?? []).map((a, i) => (
          <Reveal key={a.table.id} delay={(i % 3) * 120}>
            <TableChoice a={a} selected={picked?.table.id === a.table.id} onPick={() => setPicked(a)} />
          </Reveal>
        ))}
      </div>

      {picked && picked.quote && (
        <form onSubmit={form.handleSubmit((v) => hold.mutate(v))} className="mt-10 grid gap-4 rounded-2xl border border-brass-500/50 bg-gradient-to-b from-brass-50 to-white p-6 shadow-[var(--shadow-lift)] sm:grid-cols-2" noValidate>
          <div className="sm:col-span-2">
            <div className="eyebrow">Your booking</div>
            <div className="font-display mt-2 text-2xl font-semibold">{picked.table.name} · {time(startIso)} · {minutesLabel(duration)} · <span className="text-brass-400">{money(picked.quote.amount)}</span></div>
          </div>
          <Field label="Name" error={form.formState.errors.name?.message}><Input autoComplete="name" {...form.register("name")} /></Field>
          <Field label="Mobile (WhatsApp)" error={form.formState.errors.phone?.message}><Input inputMode="tel" autoComplete="tel" {...form.register("phone")} /></Field>
          <Field label="Email (optional)" error={form.formState.errors.email?.message}><Input type="email" autoComplete="email" {...form.register("email")} /></Field>
          <label className="flex items-start gap-2 self-end text-sm text-ink-300">
            <input type="checkbox" className="mt-1 size-4 accent-[#c9a24b]" {...form.register("agree")} />
            <span>I agree: deposit is refundable up to 4 hours before start; no-shows forfeit the deposit.</span>
          </label>
          {form.formState.errors.agree && <div className="text-xs text-red-600 sm:col-span-2">{form.formState.errors.agree.message}</div>}
          <div className="sm:col-span-2"><ErrorBox error={hold.error} /></div>
          <Button type="submit" variant="brass" size="xl" className="sm:col-span-2" loading={hold.isPending}>Pay deposit {money(picked.quote.deposit)} &amp; hold table</Button>
        </form>
      )}

      <section className="mt-14 rounded-2xl border border-line bg-white p-5 shadow-[var(--shadow-card)]">
        <h2 className="font-display mb-1 text-xl font-semibold">When will tables be free? ({day})</h2>
        <p className="mb-4 flex flex-wrap items-center gap-4 text-xs text-ink-400"><span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-emerald-100 ring-1 ring-emerald-600/20" />Free</span><span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-brass-500" />Booked</span><span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-sky-500" />In use</span><span>Updates live.</span></p>
        <div className="space-y-2 overflow-x-auto">
          {timeline.data?.tables.map((t) => {
            const open = new Date(timeline.data!.opens_at).getTime();
            const close = new Date(timeline.data!.closes_at).getTime();
            const span = close - open;
            return (
              <div key={t.table.id} className="flex min-w-[560px] items-center gap-3">
                <div className="w-24 shrink-0 text-sm font-medium">{t.table.name}</div>
                <div className="relative h-7 flex-1 overflow-hidden rounded-lg bg-emerald-50 ring-1 ring-inset ring-emerald-600/15">
                  {t.busy.map((b, i) => {
                    const l = Math.max(0, (new Date(b.start).getTime() - open) / span) * 100;
                    const w = Math.min(100 - l, ((new Date(b.end).getTime() - new Date(b.start).getTime()) / span) * 100);
                    return <div key={i} title={`${time(b.start)}–${time(b.end)}`} className={cn("absolute inset-y-1 rounded-md", b.kind === "IN_USE" ? "bg-sky-500" : "bg-brass-500")} style={{ left: `${l}%`, width: `${w}%` }} />;
                  })}
                </div>
                <div className="w-28 shrink-0 text-right text-xs text-ink-300">{t.next_free_at ? `free ${time(t.next_free_at)}` : "—"}</div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
