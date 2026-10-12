import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { get } from "@/services/api";
import type { GameType, Plan, PublicTable, Timeline } from "@/types/api";
import { useAuth } from "@/stores/auth";
import { useRealtime } from "@/hooks/useRealtime";
import { minutesLabel, money, time, todayLocal } from "@/lib/format";
import { Badge } from "@/components/ui";
import { TableArt, gameImage, tableImage } from "@/components/TableArt";
import { cn } from "@/lib/cn";
import { Table3D } from "@/components/Table3D";
import { Reveal } from "@/components/Motion";

function SectionHead({ eyebrow, title, sub }: { eyebrow: string; title: string; sub?: string }) {
  return (
    <div className="mb-8 max-w-2xl">
      <div className="eyebrow">{eyebrow}</div>
      <h2 className="font-display mt-3 text-3xl font-semibold sm:text-4xl">{title}</h2>
      {sub && <p className="mt-2 text-ink-400">{sub}</p>}
    </div>
  );
}

/** Grey shimmer blocks shown while live data is loading. */
function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-2xl bg-gradient-to-r from-stone-100 via-stone-50 to-stone-100", className)} />;
}

const STATUS_TONE = { AVAILABLE: "green", RESERVED: "amber", MAINTENANCE: "gray" } as const;

export default function Home() {
  const { branch } = useAuth();
  useRealtime(branch?.id, "public");
  const games = useQuery({ queryKey: ["public-games"], queryFn: () => get<GameType[]>("/public/game-types") });
  const plans = useQuery({ queryKey: ["public-plans"], queryFn: () => get<Plan[]>("/public/membership-plans") });
  const tables = useQuery({ queryKey: ["public-tables", branch?.id], queryFn: () => get<PublicTable[]>(`/public/branches/${branch!.id}/tables`), enabled: !!branch });
  const timeline = useQuery({ queryKey: ["timeline", branch?.id, "today"], queryFn: () => get<Timeline>("/public/timeline", { branch_id: branch!.id, day: todayLocal() }), enabled: !!branch, refetchInterval: 60000 });
  const offline = games.isError || plans.isError || tables.isError || timeline.isError || (!branch && games.isFetched && !games.data);
  const freeNow = timeline.data?.tables.filter((t) => t.status === "AVAILABLE").length ?? 0;
  const tableCount = tables.data?.length ?? timeline.data?.tables.length ?? 0;
  const fromRate = Math.min(...(games.data ?? []).map((g) => Number(g.default_hourly_rate)).filter((n) => n > 0));

  return (
    <div>
      {offline && (
        <div role="status" className="mx-auto mt-4 max-w-6xl px-4">
          <div className="flex items-center gap-3 rounded-2xl border border-amber-300/60 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <span className="size-2 shrink-0 animate-pulse rounded-full bg-amber-500" />
            Can’t reach the club server right now — live tables, prices and plans will appear automatically when it’s back.
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------ hero */}
      <section className="relative pb-10 pt-12 md:pt-16">
        <div className="mx-auto grid max-w-6xl items-end gap-8 px-4 md:grid-cols-[1.1fr_1fr] md:gap-14">
          <div className="fade-up space-y-6">
            <div className="inline-flex items-center gap-2 rounded-full border border-emerald-600/20 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
              <span className="relative flex size-2"><span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-500 opacity-60" /><span className="relative inline-flex size-2 rounded-full bg-emerald-500" /></span>
              {timeline.data ? `${freeNow} of ${timeline.data.tables.length} tables free right now` : "Live table availability"}
            </div>
            <h1 className="font-display text-5xl font-semibold leading-[1.05] tracking-tight sm:text-6xl lg:text-7xl">
              Your table,<br /><span className="text-gold-gradient italic">ready when you are.</span>
            </h1>
          </div>
          <div className="fade-up space-y-6 pb-2 [animation-delay:250ms]">
            <p className="max-w-md text-lg leading-relaxed text-ink-300">
              Snooker, pool, billiards and PS5 at {branch?.name ?? "RANU Snookers"}. See live availability, book in 60 seconds with a small deposit, and walk straight to your table.
            </p>
            <div className="flex flex-wrap gap-3">
              <Link to="/book" className="rounded-full bg-gradient-to-b from-brass-500 to-[#b48d38] px-7 py-3.5 text-sm font-bold tracking-[0.12em] text-felt-950 shadow-lg shadow-brass-500/30 transition hover:-translate-y-0.5 hover:shadow-xl hover:shadow-brass-500/40">BOOK A TABLE</Link>
              <a href="#tables" className="rounded-full border border-line bg-white px-7 py-3.5 text-sm font-semibold text-ink-100 shadow-sm transition hover:border-brass-500 hover:text-brass-600">See live tables</a>
            </div>
            <dl className="grid max-w-md grid-cols-3 gap-4 border-t border-line pt-6">
              <div><dt className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-400">Tables</dt><dd className="font-display num mt-1 text-2xl font-semibold">{tableCount || "—"}</dd></div>
              <div><dt className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-400">From</dt><dd className="font-display num mt-1 text-2xl font-semibold">{Number.isFinite(fromRate) ? `${money(fromRate)}` : "—"}<span className="text-sm font-normal text-ink-400">/hr</span></dd></div>
              <div><dt className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-400">Open</dt><dd className="font-display num mt-1 text-2xl font-semibold">{branch ? branch.opening_time : "—"}</dd></div>
            </dl>
          </div>
        </div>

        <div className="relative mx-auto max-w-7xl px-4" aria-hidden>
          <div className="absolute inset-x-0 top-24 bottom-0 bg-[radial-gradient(closest-side,rgba(201,162,75,0.2),transparent)]" />
          <Table3D wide className="fade-up h-[320px] [animation-delay:350ms] [animation-duration:2.4s] sm:h-[480px] lg:h-[640px]" />
          <div className="absolute left-6 top-28 hidden rounded-2xl border border-line bg-white/95 px-5 py-3.5 shadow-[var(--shadow-lift)] backdrop-blur sm:block lg:left-20">
            <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-400">Deposit to hold</div>
            <div className="font-display text-lg font-semibold">Pay the rest at the club</div>
          </div>
          <div className="absolute right-6 top-24 hidden size-24 place-items-center rounded-full bg-felt-950 text-center text-[11px] font-semibold uppercase leading-tight tracking-[0.14em] text-brass-500 shadow-xl ring-4 ring-white sm:grid lg:right-20">Tournament<br />grade</div>
        </div>
      </section>

      <div className="gold-rule mx-auto max-w-6xl" />

      {/* ------------------------------------------------------------ games */}
      <section id="games" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-16">
        <SectionHead eyebrow="Games" title="Choose your game" sub="Every table is maintained to match standard — fresh cloth, true cushions, polished balls." />
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {!games.data && Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-64" />)}
          {(games.data ?? []).map((g, i) => (
            <Reveal key={g.id} delay={i * 120}><Link to="/book" className="group overflow-hidden rounded-2xl border border-line bg-white shadow-[var(--shadow-card)] transition hover:-translate-y-1 hover:shadow-[var(--shadow-lift)]">
              <TableArt src={gameImage(g.code)} className="aspect-[16/10] transition duration-500 group-hover:scale-[1.03]" shade={false} />
              <div className="flex items-end justify-between gap-2 p-5">
                <div>
                  <div className="font-display text-xl font-semibold">{g.name}</div>
                  <div className="text-sm text-ink-400">from <span className="num font-semibold text-brass-400">{money(g.default_hourly_rate)}</span>/hour</div>
                </div>
                <span className="grid size-9 place-items-center rounded-full border border-line text-brass-400 transition group-hover:border-brass-500 group-hover:bg-brass-500 group-hover:text-white">→</span>
              </div>
            </Link></Reveal>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------ live tables */}
      <section id="tables" className="scroll-mt-24 bg-surface-2/70 py-16">
        <div className="mx-auto max-w-6xl px-4">
          <SectionHead eyebrow="Live" title="Tables right now" sub="Updates automatically. “Free from” shows when each table is next available today." />
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {!timeline.data && Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-52" />)}
            {(timeline.data?.tables ?? []).map((t, i) => {
              const tone = STATUS_TONE[t.status as keyof typeof STATUS_TONE] ?? "red";
              return (
                <Reveal key={t.table.id} delay={(i % 4) * 100} className="overflow-hidden rounded-2xl border border-line bg-white shadow-[var(--shadow-card)]">
                  <TableArt src={tableImage(t.table)} className="aspect-[16/9]">
                    <div className="flex h-full flex-col justify-between p-3">
                      <div className="flex justify-end"><Badge tone={tone} className="bg-white/95 shadow-sm">{t.status === "IN_USE" ? "In use" : t.status.toLowerCase()}</Badge></div>
                      <div className="font-display text-xl font-semibold text-white drop-shadow">{t.table.name}</div>
                    </div>
                  </TableArt>
                  <div className="flex items-center justify-between gap-2 px-4 py-3">
                    <div className="text-xs text-ink-400">{t.table.game_type.name} · <span className="num font-medium text-ink-100">{money(t.table.hourly_rate)}</span>/hr</div>
                    <div className={cn("text-xs", t.status === "AVAILABLE" ? "font-semibold text-emerald-700" : "text-ink-300")}>
                      {t.status === "AVAILABLE" ? "Free now" : t.next_free_at ? <>Free {time(t.next_free_at)}</> : "Full today"}
                    </div>
                  </div>
                </Reveal>
              );
            })}
          </div>
          <div className="mt-8 text-center">
            <Link to="/book" className="inline-flex rounded-full bg-ink-50 px-7 py-3 text-sm font-semibold text-white shadow-md transition hover:bg-ink-100">Book one of these tables →</Link>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------ pricing */}
      <section id="pricing" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-16">
        <SectionHead eyebrow="Pricing" title="Simple, transparent rates" />
        <div className="overflow-hidden rounded-2xl border border-line bg-white shadow-[var(--shadow-card)]">
          <table className="w-full text-sm">
            <thead className="bg-surface-2 text-left text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-400"><tr><th className="px-5 py-3">Table</th><th className="px-5 py-3">Game</th><th className="px-5 py-3 text-right">Per hour</th></tr></thead>
            <tbody className="divide-y divide-line">
              {!tables.data && Array.from({ length: 5 }, (_, i) => (
                <tr key={i}><td className="px-5 py-3.5" colSpan={3}><Skeleton className="h-4 rounded-md" /></td></tr>
              ))}
              {(tables.data ?? []).map((t) => (
                <tr key={t.id} className="transition hover:bg-brass-50/60">
                  <td className="px-5 py-3 font-medium">{t.name}</td>
                  <td className="px-5 py-3 text-ink-300">{t.game_type.name}</td>
                  <td className="num px-5 py-3 text-right font-semibold text-brass-400">{money(t.hourly_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-ink-400">Happy-hour, weekend and holiday rates apply automatically; your exact price is shown before you pay. Billing is per 15-minute block.</p>
      </section>

      {/* ------------------------------------------------------------ membership */}
      <section id="membership" className="scroll-mt-24 bg-surface-2/70 py-16">
        <div className="mx-auto max-w-6xl px-4">
          <SectionHead eyebrow="Membership" title="Play more, pay less" sub="Buy or renew at the counter — you get a RANU member card to tap at the table." />
          <div className="grid gap-5 md:grid-cols-3">
            {!plans.data && Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-80" />)}
            {(plans.data ?? []).map((p, i) => {
              const featured = p.tier === "GOLD";
              return (
                <Reveal key={p.id} delay={i * 140} className={cn("relative flex flex-col rounded-2xl border bg-white p-7 shadow-[var(--shadow-card)]", featured ? "border-brass-500 shadow-[var(--shadow-lift)] md:-translate-y-2" : "border-line")}>
                  {featured && <div className="absolute -top-3 left-7 rounded-full bg-gradient-to-r from-brass-500 to-[#b48d38] px-3 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-felt-950">Most popular</div>}
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-brass-400">{p.tier}</div>
                  <div className="font-display mt-2 text-2xl font-semibold">{p.name}</div>
                  <div className="num font-display mt-3 text-4xl font-semibold">{money(p.price)}</div>
                  <div className="text-xs text-ink-400">{p.validity_days} days{p.included_minutes ? ` · ${minutesLabel(p.included_minutes)} play time` : ""}</div>
                  <div className="my-5 h-px bg-line" />
                  <ul className="space-y-2 text-sm text-ink-300">
                    {p.benefits.map((b) => <li key={b} className="flex gap-2"><span className="mt-0.5 grid size-4 shrink-0 place-items-center rounded-full bg-brass-100 text-[10px] text-brass-600">✓</span>{b}</li>)}
                  </ul>
                </Reveal>
              );
            })}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------ about + contact */}
      <section id="about" className="mx-auto grid max-w-6xl scroll-mt-24 gap-10 px-4 py-16 md:grid-cols-2">
        <div>
          <SectionHead eyebrow="About" title="A members' club feel, open to all" />
          <p className="leading-relaxed text-ink-300">RANU Snookers is a premium cue-sports club with tournament-grade tables, a PS5 lounge, and snacks and drinks served at your table. Tournaments run every month — ask at the counter to register.</p>
        </div>
        <div id="contact" className="scroll-mt-24 rounded-2xl border border-line bg-white p-7 shadow-[var(--shadow-card)]">
          <div className="eyebrow">Contact</div>
          <div className="font-display mt-3 text-2xl font-semibold">{branch?.name ?? "RANU Snookers"}</div>
          <div className="mt-3 space-y-1.5 text-sm text-ink-300">
            {branch?.address && <div>📍 {branch.address}</div>}
            {branch?.phone && <div>📞 <a href={`tel:${branch.phone.replace(/\s/g, "")}`} className="hover:text-brass-400">{branch.phone}</a></div>}
            {branch && <div>🕒 Open daily {branch.opening_time} – {branch.closing_time}</div>}
          </div>
          <Link to="/book" className="mt-6 inline-flex rounded-full bg-gradient-to-b from-brass-500 to-[#b48d38] px-6 py-2.5 text-xs font-bold tracking-[0.14em] text-felt-950 shadow-md shadow-brass-500/30">BOOK A TABLE</Link>
        </div>
      </section>
    </div>
  );
}
