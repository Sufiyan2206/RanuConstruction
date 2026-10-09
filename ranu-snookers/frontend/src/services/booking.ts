/** Customer booking API calls + the checkout form schema (validation only — all
 * prices/availability come from the backend). */
import { z } from "zod";
import { get, post } from "@/services/api";
import type { Availability, Booking, Checkout, Timeline } from "@/types/api";

export const customerSchema = z.object({
  name: z.string().trim().min(2, "Please enter your name"),
  phone: z.string().trim().regex(/^\+?[0-9 ()-]{10,16}$/, "Enter a valid mobile number"),
  email: z.union([z.literal(""), z.string().email("Enter a valid email")]).optional(),
  agree: z.literal(true, { errorMap: () => ({ message: "Please accept the booking policy" }) }),
});
export type CustomerForm = z.infer<typeof customerSchema>;

export const fetchAvailability = (branchId: string, startIso: string, duration: number, gameTypeId?: string) =>
  get<Availability[]>("/public/availability", { branch_id: branchId, start_at: startIso, duration_minutes: duration, game_type_id: gameTypeId });

export const fetchTimeline = (branchId: string, day: string, gameTypeId?: string) =>
  get<Timeline>("/public/timeline", { branch_id: branchId, day, game_type_id: gameTypeId });

export const createHold = (body: { branch_id: string; table_id: string; start_at: string; duration_minutes: number; customer: { name: string; phone: string; email?: string } }) =>
  post<Checkout>("/public/bookings/hold", body);

export const completeMockPayment = (orderId: string) => post<{ outcome: string }>(`/public/payments/mock/${orderId}/complete`);

export const lookupBooking = (reference: string, phone: string) => post<Booking>("/public/bookings/lookup", { reference, phone });

/** Load Razorpay Checkout on demand and resolve when the customer finishes.
 * Confirmation itself always comes from the server-side webhook. */
export function openRazorpay(payload: Record<string, any>): Promise<void> {
  return new Promise((resolve, reject) => {
    const start = () => {
      const Rzp = (window as any).Razorpay;
      if (!Rzp) return reject(new Error("Payment window failed to load"));
      const rzp = new Rzp({ ...payload, handler: () => resolve(), modal: { ondismiss: () => reject(new Error("Payment cancelled")) } });
      rzp.open();
    };
    if ((window as any).Razorpay) return start();
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = start;
    s.onerror = () => reject(new Error("Could not load the payment window"));
    document.body.appendChild(s);
  });
}
