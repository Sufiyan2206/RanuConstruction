/** Minimal, accessible component kit (shadcn-style API, Tailwind styling). */
import { createContext, forwardRef, useCallback, useContext, useEffect, useRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "brass" | "outline";
const variants: Record<Variant, string> = {
  primary: "bg-ink-50 hover:bg-ink-100 text-white shadow-sm",
  secondary: "bg-white hover:bg-surface-2 text-ink-50 border border-line shadow-sm",
  ghost: "hover:bg-surface-2 text-ink-100",
  danger: "bg-red-600 hover:bg-red-700 text-white shadow-sm",
  brass: "bg-gradient-to-b from-brass-500 to-[#b48d38] hover:from-[#d4af5a] hover:to-brass-500 text-felt-950 font-semibold shadow-sm shadow-brass-500/30",
  outline: "border border-line bg-white hover:border-brass-500 hover:text-brass-600 text-ink-50",
};
const sizes = { sm: "h-8 px-3 text-sm", md: "h-10 px-4 text-sm", lg: "h-12 px-5 text-base", xl: "h-14 px-6 text-lg" };

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: keyof typeof sizes;
  loading?: boolean;
}
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant = "primary", size = "md", loading, disabled, children, ...p }, ref) => (
  <button
    ref={ref}
    className={cn("inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all disabled:opacity-50 disabled:pointer-events-none select-none", variants[variant], sizes[size], className)}
    disabled={disabled || loading}
    {...p}
  >
    {loading && <Spinner className="size-4" />}
    {children}
  </button>
));
Button.displayName = "Button";

export function Spinner({ className }: { className?: string }) {
  return <span role="status" aria-label="Loading" className={cn("inline-block size-5 animate-spin rounded-full border-2 border-current border-t-transparent", className)} />;
}

export function Card({ className, children, ...p }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-2xl border border-line bg-white p-4 shadow-[var(--shadow-card)] sm:p-5", className)} {...p}>{children}</div>;
}

export function CardTitle({ children, action, className }: { children: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("mb-3 flex items-center justify-between gap-2", className)}>
      <h2 className="text-base font-semibold text-ink-50">{children}</h2>
      {action}
    </div>
  );
}

const fieldBase = "w-full rounded-xl border border-line bg-white px-3 text-ink-50 placeholder:text-ink-500 shadow-[inset_0_1px_2px_rgb(23_20_15/0.04)] transition focus:border-brass-500 focus:ring-4 focus:ring-brass-500/15 focus:outline-none";
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn(fieldBase, "h-10", className)} {...p} />
));
Input.displayName = "Input";
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(({ className, children, ...p }, ref) => (
  <select ref={ref} className={cn(fieldBase, "h-10", className)} {...p}>{children}</select>
));
Select.displayName = "Select";
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, ref) => (
  <textarea ref={ref} className={cn(fieldBase, "min-h-20 py-2", className)} {...p} />
));
Textarea.displayName = "Textarea";

export function Field({ label, error, hint, children, className }: { label: string; error?: string; hint?: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block space-y-1.5", className)}>
      <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-400">{label}</span>
      {children}
      {hint && !error && <span className="block text-xs text-ink-400">{hint}</span>}
      {error && <span className="block text-xs text-red-600" role="alert">{error}</span>}
    </label>
  );
}

const tones = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  red: "bg-red-50 text-red-700 ring-red-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/25",
  blue: "bg-sky-50 text-sky-700 ring-sky-600/20",
  violet: "bg-violet-50 text-violet-700 ring-violet-600/20",
  gray: "bg-stone-100 text-ink-300 ring-ink-500/25",
  orange: "bg-orange-50 text-orange-700 ring-orange-600/20",
};
export type Tone = keyof typeof tones;
export function Badge({ tone = "gray", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", tones[tone], className)}>{children}</span>;
}

export function Stat({ label, value, tone, sub, onClick }: { label: string; value: ReactNode; tone?: "good" | "warn" | "bad"; sub?: ReactNode; onClick?: () => void }) {
  const color = tone === "bad" ? "text-red-600" : tone === "warn" ? "text-amber-700" : tone === "good" ? "text-emerald-700" : "text-ink-50";
  const Comp = onClick ? "button" : "div";
  return (
    <Comp onClick={onClick} className={cn("relative overflow-hidden rounded-2xl border border-line bg-white p-4 text-left shadow-[var(--shadow-card)] before:absolute before:inset-x-0 before:top-0 before:h-0.5 before:bg-gradient-to-r before:from-brass-500/0 before:via-brass-500/70 before:to-brass-500/0", onClick && "transition hover:-translate-y-0.5 hover:shadow-[var(--shadow-lift)]")}>
      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-400">{label}</div>
      <div className={cn("num mt-1 text-2xl font-semibold", color)}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-400">{sub}</div>}
    </Comp>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-brass-200 bg-brass-50/50 p-6 text-center text-sm text-ink-400">{children}</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{msg}</div>;
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-ink-50/40 p-0 backdrop-blur-sm sm:items-center sm:p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title}
        className={cn("max-h-[92vh] w-full overflow-y-auto rounded-t-3xl border border-line bg-white p-6 shadow-2xl sm:rounded-3xl", wide ? "sm:max-w-3xl" : "sm:max-w-lg")}>
        <div className="mb-4 flex items-start justify-between gap-4">
          <h3 className="font-display text-xl font-semibold">{title}</h3>
          <button onClick={onClose} className="rounded-full px-2 text-2xl leading-none text-ink-400 hover:bg-surface-2 hover:text-ink-50" aria-label="Close">×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { value: T; label: string }[] }) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto rounded-xl border border-line bg-surface-2 p-1">
      {items.map((i) => (
        <button key={i.value} role="tab" aria-selected={value === i.value} onClick={() => onChange(i.value)}
          className={cn("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm", value === i.value ? "bg-white text-ink-50 font-medium shadow-sm ring-1 ring-line" : "text-ink-400 hover:text-ink-50")}>
          {i.label}
        </button>
      ))}
    </div>
  );
}

export function DataTable({ head, children, empty }: { head: ReactNode[]; children: ReactNode; empty?: boolean }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-line bg-white shadow-[var(--shadow-card)]">
      <table className="w-full min-w-[560px] text-sm">
        <thead className="bg-surface-2 text-left text-[11px] font-semibold uppercase tracking-[0.1em] text-ink-400">
          <tr>{head.map((h, i) => <th key={i} className="px-3 py-2.5">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
      {empty && <div className="p-6 text-center text-sm text-ink-400">Nothing here yet.</div>}
    </div>
  );
}
export const Td = ({ children, className }: { children?: ReactNode; className?: string }) => <td className={cn("px-3 py-2.5 align-middle", className)}>{children}</td>;

// ---------------------------------------------------------------- toasts
type ToastT = { id: number; text: string; tone: "ok" | "err" };
const ToastCtx = createContext<(text: string, tone?: "ok" | "err") => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastT[]>([]);
  const push = useCallback((text: string, tone: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, text, tone }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-4 z-[60] flex flex-col items-center gap-2 px-4">
        {items.map((t) => (
          <div key={t.id} className={cn("pointer-events-auto rounded-xl px-4 py-2 text-sm shadow-lg", t.tone === "ok" ? "bg-ink-50 text-white ring-1 ring-brass-500/40" : "bg-red-600 text-white")}>{t.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);
