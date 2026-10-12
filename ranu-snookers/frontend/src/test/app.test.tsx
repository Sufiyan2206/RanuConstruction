import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BRANCH, GAME, TABLE, mockFetch, renderWithProviders } from "./utils";
import { customerSchema } from "@/services/booking";
import { duration, localToIso, money, minutesLabel } from "@/lib/format";
import { Login } from "@/pages/public/Auth";
import BookingStatus from "@/pages/public/BookingStatus";
import Book from "@/pages/public/Book";
import { TableCard } from "@/components/TableBoard";
import type { BoardRow, Booking } from "@/types/api";

afterEach(() => vi.unstubAllGlobals());

const publicRoutes = (url: URL) => {
  if (url.pathname.endsWith("/auth/refresh")) return { status: 401, body: { error: { code: "REFRESH_INVALID", message: "no" } } };
  if (url.pathname.endsWith("/public/branches")) return { body: [BRANCH] };
  if (url.pathname.endsWith("/public/game-types")) return { body: [GAME] };
  return undefined;
};

describe("format helpers", () => {
  it("formats rupees, durations and local ISO", () => {
    expect(money("187.5")).toContain("187.50");
    expect(money("150.00")).toBe("₹150");
    expect(duration(3725)).toBe("1h 02m");
    expect(duration(65)).toBe("01:05");
    expect(minutesLabel(90)).toBe("1h 30m");
    expect(localToIso("2026-09-23", "18:00")).toBe("2026-09-23T18:00:00+05:30");
  });
});

describe("booking form validation", () => {
  it("requires name, valid phone and policy acceptance", () => {
    expect(customerSchema.safeParse({ name: "", phone: "12", agree: false }).success).toBe(false);
    expect(customerSchema.safeParse({ name: "Arjun", phone: "9876543210", email: "", agree: true }).success).toBe(true);
    expect(customerSchema.safeParse({ name: "Arjun", phone: "9876543210", email: "bad", agree: true }).success).toBe(false);
  });
});

describe("Login", () => {
  it("validates and posts credentials", async () => {
    const f = mockFetch((url) => {
      if (url.pathname.endsWith("/auth/login")) return { status: 401, body: { error: { code: "INVALID_CREDENTIALS", message: "Invalid credentials" } } };
      return publicRoutes(url);
    });
    renderWithProviders(<Login />, { route: "/login" });
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findAllByText("Required")).toHaveLength(2);
    await userEvent.type(screen.getByLabelText(/username, email or mobile/i), "reception");
    await userEvent.type(screen.getByLabelText(/^password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials");
    expect(f.mock.calls.some(([u]) => String(u).includes("/auth/login"))).toBe(true);
  });
});

const booking = (status: Booking["status"]): Booking => ({
  id: "bk1", reference: "RBABC123", branch_id: "b1", table_id: "t1", table: TABLE, customer_id: "c1", customer_name: "Arjun", customer_phone: "919876543210",
  source: "ONLINE", status, start_at: "2026-09-24T12:30:00Z", end_at: "2026-09-24T13:30:00Z", duration_minutes: 60, hold_expires_at: new Date(Date.now() + 600000).toISOString(),
  booking_amount: "150.00", deposit_amount: "100.00", discount: "0.00", tax: "0.00", amount_paid: status === "HELD" ? "0.00" : "100.00",
  remaining_amount: status === "HELD" ? "150.00" : "50.00", payment_status: "PENDING", refund_amount: "0.00", checked_in_at: null, cancelled_at: null, cancel_reason: null, notes: null, created_at: "",
});

describe("Checkout", () => {
  it("pays the deposit and shows confirmation from the server", async () => {
    let paid = false;
    mockFetch((url) => {
      if (url.pathname.endsWith("/complete")) { paid = true; return { body: { outcome: "CONFIRMED" } }; }
      if (url.pathname.endsWith("/public/bookings/lookup")) return { body: booking(paid ? "CONFIRMED" : "HELD") };
      return publicRoutes(url);
    });
    renderWithProviders(<BookingStatus />, { route: "/booking/RBABC123", path: "/booking/:reference", state: { booking: booking("HELD"), payment_id: "p1", checkout: { mode: "mock", order_id: "mock_order_1" } } });
    const pay = await screen.findByRole("button", { name: /pay deposit/i });
    fireEvent.click(pay);
    expect(await screen.findByText("You're booked!")).toBeInTheDocument();
    expect(screen.getAllByText("RBABC123").length).toBeGreaterThan(0);
  });
});

describe("Booking flow", () => {
  it("shows live availability with backend quotes and next-free times", async () => {
    mockFetch((url) => {
      if (url.pathname.endsWith("/public/availability")) return {
        body: [
          { table: TABLE, status: "AVAILABLE", quote: { amount: "150.00", deposit: "100.00", tax: "0.00", segments: [] }, next_available_at: null, reason: null },
          { table: { ...TABLE, id: "t2", table_number: 2, name: "Table 2" }, status: "BOOKED", quote: null, next_available_at: "2026-09-24T14:30:00Z", reason: null },
        ],
      };
      if (url.pathname.endsWith("/public/timeline")) return { body: { branch_id: "b1", date: "2026-09-24", opens_at: "2026-09-24T04:30:00Z", closes_at: "2026-09-24T20:30:00Z", slot_minutes: 30, tables: [] } };
      return publicRoutes(url);
    });
    renderWithProviders(<Book />, { route: "/book" });
    expect(await screen.findByText("Table 2")).toBeInTheDocument();
    expect(screen.getByText(/Next free at/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Table 1/ }));
    expect(await screen.findByRole("button", { name: /Pay deposit/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Pay deposit/ }));
    await waitFor(() => expect(screen.getByText("Please accept the booking policy")).toBeInTheDocument());
  });
});

describe("Table dashboard card", () => {
  it("shows a running game with live bill and device health", () => {
    const row: BoardRow = {
      table: { ...TABLE, branch_id: "b1", game_type_id: "g1", status: "GAME_STARTED", peak_rate: null, off_peak_rate: null, is_active: true, is_online_bookable: true, status_changed_at: null, qr_token: "x" },
      session: { id: "s1", branch_id: "b1", table_id: "t1", booking_id: null, customer_id: null, membership_id: null, status: "ACTIVE", billing_status: "RUNNING", started_at: new Date(Date.now() - 3600_000).toISOString(),
        ended_at: null, paused_at: null, total_paused_seconds: 0, planned_end_at: null, duration_seconds: null, detection_method: "RFID", confidence_score: 1, last_activity_at: null, player_count: 2 },
      customer_name: "Ravi", elapsed_seconds: 3600, live_bill: { estimated_total: "150.00", time_amount: "150.00", products_total: "0", billed_minutes: 60, covered_minutes: 0, deposit: "0" },
      next_booking: null, devices: [{ device_id: "TABLE1_RFID", type: "RFID_READER", status: "OFFLINE", last_seen_at: null }],
    };
    renderWithProviders(<TableCard row={row} onOpen={() => {}} />);
    expect(screen.getByText("Game active")).toBeInTheDocument();
    expect(screen.getByText(/Ravi · RFID/)).toBeInTheDocument();
    expect(screen.getByText(/so far/)).toBeInTheDocument();
    expect(screen.getByText("device offline")).toBeInTheDocument();
  });
});
