/** API contract types (mirror backend Pydantic schemas). Money values are decimal strings. */
export type UUID = string;
export type Money = string;
export type ISODate = string;

export type TableStatus = "AVAILABLE" | "RESERVED" | "OCCUPIED" | "GAME_STARTED" | "PAUSED" | "MAINTENANCE" | "BLOCKED";
export type BookingStatus = "HELD" | "CONFIRMED" | "CHECKED_IN" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED" | "EXPIRED" | "NO_SHOW";
export type SessionStatus = "CREATED" | "ACTIVE" | "PAUSED" | "COMPLETED" | "CANCELLED" | "AUTO_CLOSED";
export type PaymentMethod = "CASH" | "UPI" | "CARD" | "ONLINE" | "WALLET" | "CREDIT" | "MEMBERSHIP";

export interface Page<T> { items: T[]; total: number; page: number; size: number }
export interface ApiErrorBody { error: { code: string; message: string; details?: unknown; request_id?: string } }

export interface User { id: UUID; username: string; full_name: string; email: string | null; phone: string | null; is_active: boolean; customer_id: UUID | null; last_login_at: ISODate | null }
export interface Me { user: User; roles: { code: string; name: string; branch_id: UUID | null }[]; permissions: string[]; branch_ids: UUID[] | null }
export interface TokenOut { access_token: string; expires_in: number; refresh_token?: string; user: User }

export interface Branch { id: UUID; code: string; name: string; address: string | null; phone: string | null; email: string | null; timezone: string; currency: string; opening_time: string; closing_time: string; is_active: boolean }
export interface GameType { id: UUID; code: string; name: string; description: string | null; default_hourly_rate: Money; color: string; is_active: boolean }
export interface PublicTable { id: UUID; table_number: number; name: string; game_type: GameType; hourly_rate: Money; minimum_booking_duration: number; maximum_booking_duration: number }
export interface Table extends PublicTable { branch_id: UUID; game_type_id: UUID; status: TableStatus; peak_rate: Money | null; off_peak_rate: Money | null; is_active: boolean; is_online_bookable: boolean; status_changed_at: ISODate | null; qr_token: string }

export interface PriceSegment { start: ISODate; end: ISODate; minutes: number; rate_per_hour: Money; rule: string; amount: Money }
export interface Quote { amount: Money; deposit: Money; tax: Money; segments: PriceSegment[] }
export interface Availability { table: PublicTable; status: "AVAILABLE" | "BOOKED" | "IN_USE" | "MAINTENANCE" | "UNAVAILABLE"; quote: Quote | null; next_available_at: ISODate | null; reason: string | null }
export interface Timeline {
  branch_id: UUID; date: string; opens_at: ISODate; closes_at: ISODate; slot_minutes: number;
  tables: { table: PublicTable; status: string; busy: { start: ISODate; end: ISODate; kind: string }[]; next_free_at: ISODate | null }[];
}

export interface Booking {
  id: UUID; reference: string; branch_id: UUID; table_id: UUID; table: PublicTable; customer_id: UUID; customer_name: string | null; customer_phone: string | null;
  source: string; status: BookingStatus; start_at: ISODate; end_at: ISODate; duration_minutes: number; hold_expires_at: ISODate | null;
  booking_amount: Money; deposit_amount: Money; discount: Money; tax: Money; amount_paid: Money; remaining_amount: Money; payment_status: string;
  refund_amount: Money; checked_in_at: ISODate | null; cancelled_at: ISODate | null; cancel_reason: string | null; notes: string | null; created_at: ISODate;
}
export interface Checkout { booking: Booking; payment_id: UUID | null; checkout: Record<string, any> | null }

export interface Session {
  id: UUID; branch_id: UUID; table_id: UUID; booking_id: UUID | null; customer_id: UUID | null; membership_id: UUID | null; status: SessionStatus;
  billing_status: string; started_at: ISODate | null; ended_at: ISODate | null; paused_at: ISODate | null; total_paused_seconds: number;
  planned_end_at: ISODate | null; duration_seconds: number | null; detection_method: string; confidence_score: number | null; last_activity_at: ISODate | null; player_count: number;
}
export interface LiveBill { estimated_total: Money; time_amount: Money; products_total: Money; billed_minutes: number; covered_minutes: number; deposit: Money }
export interface BoardRow {
  table: Table; session: Session | null; customer_name: string | null; elapsed_seconds: number | null; live_bill: LiveBill | null;
  next_booking: Booking | null; devices: { device_id: string; type: string; status: string; last_seen_at: ISODate | null }[];
}

export interface InvoiceLine { line_type: string; description: string; quantity: string; unit_price: Money; amount: Money }
export interface Invoice {
  id: UUID; number: string; branch_id: UUID; status: string; session_id: UUID | null; order_id: UUID | null; booking_id: UUID | null; customer_id: UUID | null;
  customer_name: string | null; subtotal: Money; discount_total: Money; tax_total: Money; total: Money; deposit_applied: Money; adjustments_total: Money;
  amount_paid: Money; balance_due: Money; issued_at: ISODate | null; paid_at: ISODate | null; lines: InvoiceLine[]; adjustments: { amount: Money; reason: string; created_at: ISODate }[];
}
export interface Payment { id: UUID; purpose: string; method: string; status: string; amount: Money; reference: string | null; paid_at: ISODate | null; provider: string | null }

export interface Alert { id: UUID; alert_type: string; severity: "INFO" | "WARNING" | "CRITICAL"; message: string; table_id: UUID | null; session_id: UUID | null; data: Record<string, unknown>; acknowledged_at: ISODate | null; created_at: ISODate }
export interface Dashboard {
  today_revenue: number | string; today_bookings: number; active_tables: number; available_tables: number; status_counts: Record<string, number>;
  active_sessions: number; pending_payments: Invoice[]; upcoming_bookings: Booking[]; ending_soon: { table_number: number; session_id: UUID; planned_end_at: ISODate }[];
  device_errors: number; alerts: Alert[]; low_stock: number; board: BoardRow[];
}

export interface Customer {
  id: UUID; name: string; phone: string; email: string | null; date_of_birth: string | null; notes: string | null; total_visits: number; total_spend: Money;
  total_play_minutes: number; last_visit_at: ISODate | null; loyalty_points: number; referral_code: string | null; marketing_opt_in: boolean; created_at: ISODate;
}
export interface Plan {
  id: UUID; code: string; name: string; tier: string; price: Money; validity_days: number; included_minutes: number; deduction_block_minutes: number;
  table_discount_percent: string; product_discount_percent: string; game_type_ids: UUID[] | null; max_minutes_per_day: number | null; benefits: string[]; is_public: boolean; is_active: boolean;
}
export interface Membership { id: UUID; code: string; card_uid: string | null; customer_id: UUID; customer: { id: UUID; name: string; phone: string } | null; plan: Plan; status: string; starts_on: string; expires_on: string; minutes_total: number; minutes_used: number; minutes_remaining: number; price_paid: Money }
export interface CustomerProfile {
  customer: Customer; total_visits: number; total_spend: Money; average_session_minutes: number; favorite_game: string | null; membership: Membership | null;
  last_visit_at: ISODate | null; outstanding: Money; loyalty_points: number; invoice_count: number;
}
export interface LedgerEntry { id: UUID; entry_type: string; amount: Money; invoice_id: UUID | null; note: string | null; created_at: ISODate }

export interface Product { id: UUID; sku: string; name: string; category_id: UUID | null; price: Money; cost_price: Money; track_stock: boolean; low_stock_threshold: number; is_active: boolean }
export interface ProductStock { product: Product; stock: string | null }
export interface Category { id: UUID; name: string; sort_order: number }
export interface OrderItem { id: UUID; product_id: UUID; name: string; quantity: string; unit_price: Money; amount: Money; status: string; created_at: ISODate }
export interface Order { id: UUID; number: string; session_id: UUID | null; status: string; subtotal: Money; items: OrderItem[] }
export interface InventoryTxn { id: UUID; product_id: UUID; txn_type: string; quantity: string; unit_cost: Money | null; balance_after: string; reference: string | null; note: string | null; created_at: ISODate }

export interface Device { id: UUID; device_id: string; name: string; device_type: string; table_id: UUID | null; status: string; last_seen_at: ISODate | null; firmware_version: string | null; configuration: Record<string, unknown>; is_enabled: boolean; api_key_prefix: string }
export interface DeviceEvent { id: UUID; event_id: string; event_type: string; confidence: number | null; occurred_at: ISODate; received_at: ISODate; outcome: string | null; detail: string | null; table_id: UUID | null }
export interface DetectionState { table_id: UUID; table_number: number; state: string; score: number; activity_events: number; first_activity_at: ISODate | null; last_activity_at: ISODate | null; identified_customer_id: UUID | null; signals: { source: string; confidence: number; at: ISODate }[] }

export interface Approval { id: UUID; approval_type: string; status: string; amount: Money | null; reason: string; invoice_id: UUID | null; order_item_id: UUID | null; requested_by_id: UUID; created_at: ISODate; resolution_note: string | null }
export interface Shift { id: UUID; branch_id: UUID; user_id: UUID; status: string; opened_at: ISODate; closed_at: ISODate | null; opening_cash: Money; cash_sales: Money; cash_expenses: Money; expected_cash: Money; counted_cash: Money | null; variance: Money | null; notes: string | null }
export interface ExpenseCategory { id: UUID; code: string; name: string; color: string }
export interface Expense { id: UUID; category: ExpenseCategory; amount: Money; description: string; paid_to: string | null; method: string; expense_date: string; is_void: boolean; void_reason: string | null; created_at: ISODate }
export interface AuditLog { id: UUID; username: string | null; action: string; entity_type: string; entity_id: string | null; before: Record<string, unknown> | null; after: Record<string, unknown> | null; reason: string | null; ip: string | null; request_id: string | null; created_at: ISODate }
export interface Tournament { id: UUID; name: string; format: string; status: string; entry_fee: Money; prize_pool: Money; max_players: number; starts_on: string | null; winner_player_id: UUID | null; game_type_id: UUID }
export interface TournamentPlayer { id: UUID; display_name: string; seed: number | null; group_no: number | null; wins: number; losses: number; eliminated: boolean; fee_paid: boolean }
export interface TournamentMatch { id: UUID; stage: string; round_no: number; match_no: number; group_no: number | null; player1_id: UUID | null; player2_id: UUID | null; score1: number | null; score2: number | null; winner_id: UUID | null; status: string; table_id: UUID | null }
export interface PricingRule { id: UUID; branch_id: UUID; name: string; kind: string; game_type_id: UUID | null; table_id: UUID | null; day_type: string; days_of_week: number[] | null; start_time: string | null; end_time: string | null; valid_from: string | null; valid_to: string | null; customer_segment: string; rate_per_hour: Money | null; rate_multiplier: number | null; priority: number; is_active: boolean }
export interface UserWithRoles extends User { roles: { code: string; name: string; branch_id: UUID | null }[] }
export interface Role { id: UUID; code: string; name: string; description: string; is_system: boolean; permissions: { code: string; description: string }[] }
