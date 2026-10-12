/** Checkout + confirmation page. Shows the hold countdown, opens the payment
 * provider, then polls until the server (webhook) confirms the booking. */
import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { completeMockPayment, lookupBooking, openRazorpay } from "@/services/booking";
import type { Booking, Checkout } from "@/types/api";
import { Button, Card, ErrorBox, Field, Input } from "@/components/ui";
import { StatusBadge } from "@/components/status";
import { useNow } from "@/hooks/useRealtime";
import { dateTime, money, time, waLink } from "@/lib/format";

export default function BookingStatus() {
  const { reference = "" } = useParams();
  const state = useLocation().state as Checkout | null;
  const [phone, setPhone] = useState(state?.booking.customer_phone ?? "");
  const [lookupPhone, setLookupPhone] = useState(state?.booking.customer_phone ?? "");
  const now = useNow(1000);

  const q = useQuery({
    queryKey: ["booking", reference, lookupPhone],
    queryFn: () => lookupBooking(reference, lookupPhone),
    enabled: !!lookupPhone,
    initialData: state?.booking,
    refetchInterval: (query) => ((query.state.data as Booking | undefined)?.status === "HELD" ? 2500 : false),
  });
  const b = q.data;
  const pay = useMutation({
    mutationFn: async () => {
      const c = state?.checkout;
      if (!c) throw new Error("Checkout session expired — please book again.");
      if (c.mode === "mock") await completeMockPayment(c.order_id);
      else if (c.mode === "razorpay") await openRazorpay(c);
      else throw new Error("This payment method must be completed on the provider page.");
    },
    onSuccess: () => q.refetch(),
  });
  useEffect(() => { if (b?.status === "CONFIRMED") window.scrollTo(0, 0); }, [b?.status]);

  if (!b) {
    return (
      <div className="mx-auto max-w-md px-4 py-16">
        <Card>
          <h1 className="mb-4 text-xl font-semibold">Find booking {reference}</h1>
          <Field label="Mobile number used for booking"><Input value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" /></Field>
          <Button className="mt-4 w-full" onClick={() => setLookupPhone(phone)}>Show booking</Button>
          <ErrorBox error={q.error} />
        </Card>
      </div>
    );
  }
  const left = b.hold_expires_at ? Math.max(0, Math.floor((new Date(b.hold_expires_at).getTime() - now) / 1000)) : 0;
  const confirmed = ["CONFIRMED", "CHECKED_IN", "IN_PROGRESS", "COMPLETED"].includes(b.status);

  return (
    <div className="mx-auto max-w-lg px-4 py-10">
      <Card className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs text-ink-400">Booking reference</div>
            <div className="text-2xl font-bold tracking-widest text-brass-400">{b.reference}</div>
          </div>
          <StatusBadge status={b.status} />
        </div>
        <div className="rounded-xl bg-surface-2 p-4">
          <div className="text-lg font-semibold">{b.table.name} · {b.table.game_type.name}</div>
          <div className="text-sm text-ink-300">{dateTime(b.start_at)} – {time(b.end_at)}</div>
          <dl className="num mt-3 grid grid-cols-2 gap-y-1 text-sm">
            <dt className="text-ink-400">Total (estimate)</dt><dd className="text-right">{money(b.booking_amount)}</dd>
            <dt className="text-ink-400">Deposit</dt><dd className="text-right">{money(b.deposit_amount)}</dd>
            <dt className="text-ink-400">Paid</dt><dd className="text-right">{money(b.amount_paid)}</dd>
            <dt className="font-semibold">Pay at club</dt><dd className="text-right font-semibold">{money(b.remaining_amount)}</dd>
          </dl>
        </div>

        {b.status === "HELD" && (
          <>
            <div className="text-center text-sm text-amber-800">Table held for you · <span className="num font-semibold">{Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}</span> left to pay</div>
            <Button variant="brass" size="xl" className="w-full" loading={pay.isPending} disabled={left === 0} onClick={() => pay.mutate()}>
              Pay deposit {money(b.deposit_amount)}{state?.checkout?.mode === "mock" ? " (demo)" : ""}
            </Button>
            <ErrorBox error={pay.error} />
          </>
        )}
        {confirmed && (
          <div className="space-y-3 text-center">
            <div className="text-3xl">🎱</div>
            <div className="text-lg font-semibold text-emerald-700">You're booked!</div>
            <p className="text-sm text-ink-300">Show reference <b>{b.reference}</b> at the counter. We've sent the details to your WhatsApp.</p>
            <a className="inline-block text-sm text-brass-400 underline" target="_blank" rel="noreferrer"
              href={waLink("", `My RANU booking ${b.reference}: ${b.table.name}, ${dateTime(b.start_at)}`)}>Share booking</a>
          </div>
        )}
        {(b.status === "EXPIRED" || b.status === "CANCELLED") && (
          <div className="text-center text-sm text-ink-300">This booking is {b.status.toLowerCase()}. {Number(b.refund_amount) > 0 && `Refund of ${money(b.refund_amount)} initiated.`} <Link className="text-brass-400 underline" to="/book">Book again</Link></div>
        )}
      </Card>
    </div>
  );
}
