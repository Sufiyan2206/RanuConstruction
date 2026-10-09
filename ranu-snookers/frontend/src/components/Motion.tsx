/** Motion helpers: slow scroll-reveal and 3D tilt-on-hover. Both respect reduced-motion via CSS. */
import { useEffect, useRef, type CSSProperties, type ElementType, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Reveal({ children, className, delay = 0, as: Tag = "div" }: { children: ReactNode; className?: string; delay?: number; as?: ElementType }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") { el.classList.add("in"); return; }
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { el.classList.add("in"); io.disconnect(); }
    }, { threshold: 0.12, rootMargin: "0px 0px -40px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return <Tag ref={ref} className={cn("reveal", className)} style={{ transitionDelay: `${delay}ms` }}>{children}</Tag>;
}

const MAX_TILT = 7; // degrees

/** Spread onto any element to make it tilt toward the pointer in 3D, with a soft glare. Add <TiltGlare/> inside. */
export function useTilt<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const onPointerMove = (e: React.PointerEvent<T>) => {
    const el = ref.current;
    if (!el || e.pointerType === "touch") return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width;
    const py = (e.clientY - r.top) / r.height;
    el.style.transform = `perspective(900px) rotateX(${(0.5 - py) * MAX_TILT * 2}deg) rotateY(${(px - 0.5) * MAX_TILT * 2}deg) translateZ(0) scale(1.02)`;
    el.style.setProperty("--gx", `${px * 100}%`);
    el.style.setProperty("--gy", `${py * 100}%`);
  };
  const onPointerLeave = () => { if (ref.current) ref.current.style.transform = ""; };
  return { ref, onPointerMove, onPointerLeave, className: "tilt" } as const;
}

export const TiltGlare = () => <span aria-hidden className="tilt-glare" />;

export type MotionStyle = CSSProperties & Record<`--${string}`, string | number>;
