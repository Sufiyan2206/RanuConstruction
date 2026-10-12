/** Cinematic 3D snooker table: a slow-motion break shot on loop (pure CSS 3D, no WebGL).
 *  Positions are % of the table plane (felt image is 1600x900). */
import { useEffect, useMemo, useRef } from "react";
import type { MotionStyle } from "@/components/Motion";
import { cn } from "@/lib/cn";

const BALL = 2.8;           // ball diameter, % of table width
const ASPECT = 16 / 9;
const BALL_H = BALL * ASPECT; // same diameter in % of table height

const COLORS = { red: "#c8102e", yellow: "#f2c230", green: "#1f8a3c", brown: "#7a4a22", blue: "#1f4fbf", pink: "#ee7aa6", black: "#151515", white: "#f7f5ef" };

// Spots, derived from the felt artwork geometry.
const BAULK_X = 24.3;
const D_R = 12.7;
const PINK = { x: 71.8, y: 50 };
const APEX_X = PINK.x + BALL + 0.3;
const CUE_START = { x: 18.5, y: 57 };
const HIT = { x: APEX_X - BALL * 0.95, y: 50 + BALL_H * 0.12 };
const CUE_REST = { x: 58, y: 36 };

/** Deterministic pseudo-random so the break looks the same every loop. */
function rand(seed: number) {
  const x = Math.sin(seed * 9301 + 49297) * 233280;
  return x - Math.floor(x);
}

function useReds() {
  return useMemo(() => {
    const reds: { x0: number; y0: number; x1: number; y1: number }[] = [];
    const cx = APEX_X + 4, cy = 50;
    let i = 0;
    for (let row = 0; row < 5; row++) {
      for (let k = 0; k <= row; k++) {
        const x0 = APEX_X + row * BALL * 0.875;
        const y0 = 50 + (k - row / 2) * (BALL_H + 0.15);
        const ang = Math.atan2((y0 - cy) * 1.6, x0 - cx + 3) + (rand(i) - 0.5) * 1.6;
        const dist = 9 + rand(i + 40) * 20;
        const x1 = Math.min(91, Math.max(9, x0 + Math.cos(ang) * dist * 1.1 - 2));
        const y1 = Math.min(85, Math.max(15, y0 + Math.sin(ang) * dist * 1.9));
        reds.push({ x0, y0, x1, y1 });
        i++;
      }
    }
    return reds;
  }, []);
}

function Ball({ x, y, color, className, style }: { x: number; y: number; color: string; className?: string; style?: MotionStyle }) {
  return (
    <div className={cn("ball3d", className)} style={{ left: `${x}%`, top: `${y}%`, width: `${BALL}%`, "--c": color, ...style } as MotionStyle}>
      <div className="ball3d-shadow" />
      <div className="ball3d-sphere" />
    </div>
  );
}

export function Table3D({ className, wide }: { className?: string; wide?: boolean }) {
  const plane = useRef<HTMLDivElement>(null);
  const reds = useReds();

  // --u = 1% of the plane width in px, used for the ball's lift off the felt.
  useEffect(() => {
    const el = plane.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => el.style.setProperty("--u", `${e.contentRect.width / 100}px`));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const pct = (n: number) => `${n}%`;
  const aimDeg = (Math.atan2((HIT.y - CUE_START.y) / ASPECT, HIT.x - CUE_START.x) * 180) / Math.PI;

  return (
    <div className={cn("scene3d relative", className)} aria-hidden>
      {/* hanging lamp + light cone */}
      <div className="lamp-sway pointer-events-none absolute left-1/2 top-0 z-10 -translate-x-1/2">
        <div className={cn("mx-auto h-5 w-px bg-ink-300/60 sm:h-10", wide && "lg:h-14")} />
        <div className={cn("relative mx-auto h-6 w-28 rounded-t-[50%] bg-gradient-to-b from-felt-800 to-felt-950 shadow-lg sm:h-9 sm:w-56", wide && "lg:h-12 lg:w-80")}>
          <div className="absolute inset-x-3 bottom-0 h-1 rounded-full bg-gradient-to-r from-brass-500/0 via-brass-500 to-brass-500/0" />
        </div>
        <div className={cn("light-pulse mx-auto -mt-1 h-40 w-[17rem] sm:h-56 bg-[radial-gradient(ellipse_at_top,rgba(255,236,190,0.55),rgba(255,236,190,0.12)_45%,transparent_70%)] blur-sm [clip-path:polygon(38%_0,62%_0,100%_100%,0_100%)] sm:w-[34rem]", wide && "lg:h-72 lg:w-[52rem]")} />
      </div>

      <div className={cn("relative mx-auto pt-[16%]", wide ? "w-[min(980px,80%)] lg:pt-[11%]" : "w-[min(720px,84%)]")}>
        <div ref={plane} className="table3d aspect-[16/9] w-full">
          <div className="table3d-shadow" />
          {/* rail thickness */}
          <div className="table3d-side left-[1.5%] right-[1.5%] top-full h-[7%] origin-top [transform:rotateX(-90deg)]" />
          <div className="table3d-side bottom-[2%] top-[2%] left-full w-[4%] origin-left [transform:rotateY(90deg)]" />
          <div className="table3d-side bottom-[2%] top-[2%] right-full w-[4%] origin-right [transform:rotateY(-90deg)]" />
          <div className="table3d-felt" />

          {/* colours on their spots */}
          <Ball x={BAULK_X} y={50 - D_R} color={COLORS.green} />
          <Ball x={BAULK_X} y={50} color={COLORS.brown} />
          <Ball x={BAULK_X} y={50 + D_R} color={COLORS.yellow} />
          <Ball x={50} y={50} color={COLORS.blue} />
          <Ball x={PINK.x} y={PINK.y} color={COLORS.pink} />
          <Ball x={85.7} y={50} color={COLORS.black} />

          {/* the pack, breaking in slow motion */}
          {reds.map((r, i) => (
            <Ball key={i} x={r.x0} y={r.y0} color={COLORS.red} className="red3d"
              style={{ "--x0": pct(r.x0), "--y0": pct(r.y0), "--x1": pct(r.x1), "--y1": pct(r.y1), animationDelay: `${(i % 5) * 18}ms` }} />
          ))}

          {/* impact ripple at the apex */}
          <div className="impact3d absolute size-[7%] -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white/80 bg-white/25 blur-[1px]"
            style={{ left: pct(HIT.x + BALL / 2), top: pct(HIT.y), aspectRatio: 1, height: "auto" }} />

          {/* cue ball + cue */}
          <Ball x={CUE_START.x} y={CUE_START.y} color={COLORS.white} className="cueball3d"
            style={{ "--x0": pct(CUE_START.x), "--y0": pct(CUE_START.y), "--xh": pct(HIT.x), "--yh": pct(HIT.y), "--x1": pct(CUE_REST.x), "--y1": pct(CUE_REST.y) }} />
          <div className="absolute h-[1.5%] w-[30%]" style={{ left: pct(CUE_START.x - 30 - BALL * 0.7), top: pct(CUE_START.y), transformOrigin: "100% 50%", transform: `translateY(-50%) rotate(${aimDeg}deg)`, translate: `0 0` }}>
            <div className="cue3d h-full w-full rounded-full bg-[linear-gradient(90deg,#1a1410_0%,#2b1a10_28%,#c9a24b_29%,#2b1a10_31%,#e2c28c_42%,#f0dcb4_97%,#f6f1e6_98.5%,#3a6ea8_100%)] shadow-[0_6px_10px_rgba(0,0,0,.35)] [clip-path:polygon(0_0,100%_32%,100%_68%,0_100%)]" />
          </div>
        </div>
      </div>
    </div>
  );
}
