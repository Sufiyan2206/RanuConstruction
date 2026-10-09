import { useState } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import { useAuth } from "@/stores/auth";
import { cn } from "@/lib/cn";

const NAV = [
  { to: "/#games", label: "Games" },
  { to: "/#tables", label: "Tables" },
  { to: "/#pricing", label: "Pricing" },
  { to: "/#membership", label: "Membership" },
  { to: "/#about", label: "About" },
  { to: "/#contact", label: "Contact" },
];

export function Logo({ light }: { light?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2.5" aria-label="RANU Snookers home">
      <span className="grid size-9 shrink-0 place-items-center rounded-full bg-felt-950 ring-2 sm:size-10 ring-brass-500 ring-offset-2 ring-offset-transparent">
        <span className="grid size-5 place-items-center rounded-full bg-gradient-to-br from-white to-stone-200 text-[10px] font-black text-felt-950 shadow-inner">R</span>
      </span>
      <span className={cn("font-display whitespace-nowrap text-lg font-semibold tracking-wide sm:text-xl", light ? "text-white" : "text-ink-50")}>
        RANU <span className="text-gold-gradient">Snookers</span>
      </span>
    </Link>
  );
}

export function PublicLayout() {
  const { me, isStaff, branch } = useAuth();
  const [open, setOpen] = useState(false);
  return (
    <div className="felt-bg flex min-h-full flex-col overflow-x-clip">
      <header className="sticky top-0 z-40 border-b border-line/80 bg-white/85 backdrop-blur-md">
        <div className="mx-auto flex h-[72px] max-w-6xl items-center justify-between gap-4 px-4">
          <Logo />
          <nav className="hidden items-center gap-7 text-sm font-medium text-ink-300 md:flex" aria-label="Main">
            {NAV.map((n) => (
              <a key={n.to} href={n.to} className="relative py-1 transition-colors after:absolute after:inset-x-0 after:-bottom-0.5 after:h-px after:origin-left after:scale-x-0 after:bg-brass-500 after:transition-transform hover:text-ink-50 hover:after:scale-x-100">{n.label}</a>
            ))}
          </nav>
          <div className="flex items-center gap-3">
            {me ? (
              <NavLink to={isStaff ? "/admin" : "/my/bookings"} className="hidden text-sm font-medium text-ink-300 hover:text-ink-50 sm:block">{isStaff ? "Staff app" : "My bookings"}</NavLink>
            ) : (
              <NavLink to="/login" className="hidden text-sm font-medium text-ink-300 hover:text-ink-50 sm:block">Login</NavLink>
            )}
            <Link to="/book" className="whitespace-nowrap rounded-full bg-gradient-to-b from-brass-500 to-[#b48d38] px-4 py-2.5 text-[11px] font-bold tracking-[0.12em] sm:px-5 sm:text-xs text-felt-950 shadow-md shadow-brass-500/30 transition hover:shadow-lg hover:shadow-brass-500/40">BOOK A TABLE</Link>
            <button className="rounded-lg p-2 text-ink-300 hover:bg-surface-2 md:hidden" aria-label="Menu" aria-expanded={open} onClick={() => setOpen(!open)}>☰</button>
          </div>
        </div>
        <nav className={cn("border-t border-line bg-white px-4 py-2 md:hidden", !open && "hidden")} aria-label="Mobile">
          {NAV.map((n) => <a key={n.to} href={n.to} onClick={() => setOpen(false)} className="block border-b border-line/60 py-3 text-ink-100 last:border-0">{n.label}</a>)}
          <Link to={me ? (isStaff ? "/admin" : "/my/bookings") : "/login"} onClick={() => setOpen(false)} className="block py-3 font-medium text-brass-400">{me ? "My account" : "Login"}</Link>
        </nav>
      </header>
      <main className="flex-1"><Outlet /></main>
      <footer className="mt-10 bg-felt-950 text-white/70">
        <div className="h-0.5 bg-gradient-to-r from-transparent via-brass-500 to-transparent" />
        <div className="mx-auto grid max-w-6xl gap-8 px-4 py-12 sm:grid-cols-3">
          <div className="space-y-3">
            <Logo light />
            <p className="max-w-xs text-sm leading-relaxed text-white/60">A premium cue-sports club — tournament-grade tables, PS5 lounge and service at your table.</p>
          </div>
          <div className="text-sm">
            <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-brass-500">Visit</div>
            <div className="text-white/80">{branch?.name ?? "RANU Snookers"}</div>
            {branch?.address && <div>{branch.address}</div>}
            {branch?.phone && <div>{branch.phone}</div>}
            {branch && <div>Open daily {branch.opening_time} – {branch.closing_time}</div>}
          </div>
          <div className="text-sm">
            <div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-brass-500">Play</div>
            <div className="flex flex-col gap-1.5">
              <Link to="/book" className="hover:text-white">Book a table</Link>
              <a href="/#membership" className="hover:text-white">Membership</a>
              <Link to={me ? "/my/bookings" : "/login"} className="hover:text-white">{me ? "My bookings" : "Login"}</Link>
            </div>
          </div>
        </div>
        <div className="border-t border-white/10 px-4 py-5 text-center text-xs text-white/40">© {new Date().getFullYear()} RANU Snookers · Book online, play on time.</div>
      </footer>
    </div>
  );
}
