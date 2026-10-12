/** Formatting helpers. The API speaks UTC; we display in the branch timezone. */
export const CLUB_TZ = "Asia/Kolkata";

const inr0 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const inr2 = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function money(v: string | number | null | undefined): string {
  const n = typeof v === "number" ? v : parseFloat(v ?? "0");
  const x = Number.isFinite(n) ? n : 0;
  return (Number.isInteger(x) ? inr0 : inr2).format(x);
}

export function num(v: string | number | null | undefined): number {
  const n = typeof v === "number" ? v : parseFloat(v ?? "0");
  return Number.isFinite(n) ? n : 0;
}

export function time(iso: string | null | undefined, tz = CLUB_TZ): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: tz }).format(new Date(iso));
}

export function date(iso: string | null | undefined, tz = CLUB_TZ): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone: tz }).format(new Date(iso));
}

export function dateTime(iso: string | null | undefined, tz = CLUB_TZ): string {
  if (!iso) return "—";
  return `${date(iso, tz)}, ${time(iso, tz)}`;
}

export function duration(seconds: number | null | undefined): string {
  const s = Math.max(0, Math.floor(seconds ?? 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

export function minutesLabel(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? (m ? `${h}h ${m}m` : `${h}h`) : `${m}m`;
}

/** YYYY-MM-DD of "today" in the club timezone. */
export function todayLocal(offsetDays = 0, tz = CLUB_TZ): string {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
}

/** Build an ISO string with the club's UTC offset from a local date + HH:MM (IST has no DST). */
export function localToIso(day: string, hhmm: string, offset = "+05:30"): string {
  return `${day}T${hhmm}:00${offset}`;
}

export function titleCase(s: string): string {
  return s.toLowerCase().replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function waLink(phone: string, text: string): string {
  return `https://wa.me/${phone.replace(/\D/g, "")}?text=${encodeURIComponent(text)}`;
}
