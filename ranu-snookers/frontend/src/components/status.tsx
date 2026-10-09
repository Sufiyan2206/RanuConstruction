import { Badge, type Tone } from "@/components/ui";
import { titleCase } from "@/lib/format";

export const TABLE_TONE: Record<string, Tone> = {
  AVAILABLE: "green", RESERVED: "amber", OCCUPIED: "red", GAME_STARTED: "blue", PAUSED: "orange", MAINTENANCE: "gray", BLOCKED: "gray",
};
export const TABLE_LABEL: Record<string, string> = {
  AVAILABLE: "Available", RESERVED: "Reserved", OCCUPIED: "Occupied", GAME_STARTED: "Game active", PAUSED: "Paused", MAINTENANCE: "Maintenance", BLOCKED: "Blocked",
};
export const TABLE_BORDER: Record<string, string> = {
  AVAILABLE: "border-emerald-500/30", RESERVED: "border-amber-400/70", OCCUPIED: "border-red-400/70", GAME_STARTED: "border-sky-400/80",
  PAUSED: "border-orange-400/80", MAINTENANCE: "border-line", BLOCKED: "border-line",
};

const GENERIC: Record<string, Tone> = {
  CONFIRMED: "green", HELD: "amber", CHECKED_IN: "blue", IN_PROGRESS: "blue", COMPLETED: "gray", CANCELLED: "red", EXPIRED: "gray", NO_SHOW: "red",
  PAID: "green", PARTIALLY_PAID: "amber", PENDING: "amber", ISSUED: "amber", VOID: "gray", FAILED: "red", REFUNDED: "violet",
  ONLINE: "green", OFFLINE: "red", ERROR: "red", ACTIVE: "blue", EXPIRING: "amber", SUSPENDED: "orange", APPROVED: "green", REJECTED: "red",
  CRITICAL: "red", WARNING: "amber", INFO: "blue", OPEN: "green", CLOSED: "gray",
};

export function TableStatusBadge({ status }: { status: string }) {
  return <Badge tone={TABLE_TONE[status] ?? "gray"}>{status === "MAINTENANCE" ? "⚠ " : ""}{TABLE_LABEL[status] ?? titleCase(status)}</Badge>;
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={GENERIC[status] ?? "gray"}>{titleCase(status)}</Badge>;
}
