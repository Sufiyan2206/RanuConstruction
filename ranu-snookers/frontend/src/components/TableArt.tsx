/** Table imagery: illustrated top-down tables per game, overridable with real photos. */
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

/** Real photos, if you have them. Put the files in `public/tables/` and list them here.
 *  A per-table photo ("table-<number>") wins over a per-game photo (game code). Example:
 *    "table-1": "/tables/table-1.jpg",
 *    SNOOKER: "/tables/snooker.jpg",
 */
const PHOTOS: Record<string, string> = {};

const ART: Record<string, string> = { SNOOKER: "snooker", POOL: "pool", BILLIARDS: "billiards", PS5: "ps5" };

type TableLike = { table_number?: number; game_type: { code: string } };

export function tableImage(t: TableLike): string {
  const code = t.game_type.code.toUpperCase();
  return PHOTOS[`table-${t.table_number}`] ?? PHOTOS[code] ?? `/tables/${ART[code] ?? "snooker"}.svg`;
}

export function gameImage(code: string): string {
  const c = code.toUpperCase();
  return PHOTOS[c] ?? `/tables/${ART[c] ?? "snooker"}.svg`;
}

/** Image block with a bottom shade so text placed on it stays readable. */
export function TableArt({ src, className, children, shade = true }: { src: string; className?: string; children?: ReactNode; shade?: boolean }) {
  return (
    <div className={cn("table-art relative overflow-hidden", className)} style={{ backgroundImage: `url(${src})` }}>
      {shade && <div aria-hidden className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/15 to-transparent" />}
      {children && <div className="relative h-full">{children}</div>}
    </div>
  );
}
