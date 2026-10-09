# RANU Club Management Platform — User Manual

This manual is for the people who use the system every day: **customers**, **counter staff /
receptionists**, **managers** and **club admins**. No technical knowledge is needed.

Contents
1. Customers — booking a table online
2. Staff — signing in and the dashboard
3. Starting, running and ending a game
4. Taking payment, discounts, receipts
5. Bookings at the counter (phone / walk-in)
6. Food, drinks & counter sales (POS)
7. Customers, dues and memberships
8. Cash shift and expenses
9. Devices and automatic detection
10. Manager & admin tasks (reports, settings, users, audit)
11. What to do when… (troubleshooting)

---

## 1. Customers — booking a table online

1. Open the club website and tap **BOOK A TABLE**.
2. Choose **Game** (Snooker, Pool, Billiards, PS5 — or All), **Date**, **Start time** and **Duration**.
3. The list shows every table:
   * **Available** – with the exact price (happy-hour/weekend rates are already applied) and the deposit to pay now.
   * **Booked / In use** – with **Next free at …** so you know when it becomes available.
   * The bar chart at the bottom ("When will tables be free?") shows the whole day at a glance.
4. Tap a table, enter your **name and mobile (WhatsApp)**, accept the policy, tap **Pay deposit & hold table**.
5. The table is **held for 10 minutes** while you pay. Pay the deposit (UPI / card).
6. You'll see **"You're booked!"** with your **booking reference** (e.g. `RB7K2QXM`) and get a WhatsApp/email confirmation.
7. At the club, show the reference at the counter. The deposit is deducted from your final bill.

**Cancelling:** Sign in (or create an account with the same mobile) → *My bookings* → **Cancel**.
Cancel at least **4 hours before** start for a full deposit refund (the club can change this).
No-shows (15 minutes late without notice) forfeit the deposit.

**QR at the table:** scan the sticker on the table, enter your name and mobile, tap **Start game**.
**Member card:** tap your RANU card on the table reader – the game starts and your membership hours are used.

---

## 2. Staff — signing in and the dashboard

* **Sign in** at `/login` with username + password, or use the **Staff PIN** tab for quick counter login.
* After 5 wrong attempts the account is locked for 15 minutes.
* The top bar shows **● Live** when real-time updates are connected. If it shows *Reconnecting*, the screen
  still works; it just refreshes every 30 seconds until the connection is back.

The **Dashboard** answers the six counter questions in seconds:

| Question | Where to look |
|----------|---------------|
| What tables are free? | Green cards + "Available" count |
| What tables are running? | Blue cards show a running clock and the bill so far |
| Who is arriving? | *Arriving (next 3h)* list with **Check in** buttons |
| Who needs payment? | *Needs payment* list – tap to open the bill |
| Which games are ending? | "Ends 7:30 pm" turns amber 10 minutes before; *Ending soon* list |
| Is any device offline? | Red dot + "device offline" on the table card; *Device errors* tile |

Table colours: 🟢 Available · 🟡 Reserved (booking soon) · 🔴 Occupied (customer checked in) · 🔵 Game active · 🟠 Paused · ⚪ Maintenance.

---

## 3. Starting, running and ending a game

**Tap any table card** to open its action sheet.

*Start a walk-in:*
1. Search the customer by name/phone or tap **+ New customer** (optional but recommended — it enables dues, loyalty and WhatsApp receipts).
2. Choose **Planned time** (or *Open*).
3. Tap **Start game**. Billing starts now.
   * If the table is reserved for someone else soon, the system stops you (*TABLE_RESERVED*). Tick **Start anyway** only if the manager agrees – it is audited.

*Booked customer arrives:* Dashboard → *Arriving* → **Check in** (or Bookings → Check in). The table turns red (Occupied).
Then tap the table → **Start game**. The session is linked to the booking and the deposit is applied automatically.

*While playing:* **Pause** (tea break – paused time is not billed) / **Resume**, **+30 / +60 min** (only if no other
booking follows), **Add items** (food & drinks go on the table's tab).

*Ending:* tap **Stop game & bill**. The final bill is generated instantly:
time is charged in **15-minute blocks** (e.g. 61 minutes = 75 minutes), at the rate in force for each part
of the game (e.g. part in happy hour, part at normal rate). Members' hours are used first.

*Mistakes:* **Cancel without charge** (wrong table started) needs a reason; cancelling a *running* game needs a manager.

---

## 4. Taking payment, discounts, receipts

In the bill window:
1. The **Balance due** is already reduced by any online deposit.
2. Choose the method (Cash, UPI, Card, Wallet, **Credit (Due)**) and amount. For UPI/Card type the transaction reference.
3. **+ Split payment** lets you take e.g. ₹300 cash + ₹200 UPI.
4. Tap **Collect**. When the balance reaches ₹0 the bill turns **Paid**, the customer gets loyalty points, and their visit count updates.

* **Credit (Due)** puts the amount on the customer's dues account (a registered customer is required).
* **Discount / correction:** enter amount + reason. Within your limit it is applied immediately; above it, a manager must approve (Approvals & Alerts). The original bill lines are never changed – a credit note line is added.
* **Print receipt** (80 mm thermal printers supported) or **Share on WhatsApp**.
* Paid bills cannot be edited or voided – a manager issues a refund instead.

---

## 5. Bookings at the counter (phone / walk-in)

Bookings → **+ Phone / counter booking** → customer, table, date, time, duration, optional deposit (cash/UPI/card) → **Confirm**.
Other actions on each booking: **Check in**, **Move** (reschedule – only if the new time is free),
**Cancel** (refund follows the policy), **No-show** (deposit kept). The system marks no-shows automatically 15 minutes after start.

---

## 6. Food, drinks & counter sales (POS)

* **On a table:** table → **Add items** → tap + for each product → **Add**. Stock is deducted immediately; out-of-stock items can't be added.
* **Removing an item** needs manager approval (or a manager login).
* **Counter sale** (no table): POS → tap products → optional customer → **Create bill** → take payment.

Inventory (managers): **Stock movement** → *Purchase (receive)* with supplier invoice # and cost, *Damaged*, *Return to supplier*, *Count adjustment*.
Every movement is recorded in the **Ledger** — stock is never simply overwritten. Low-stock items raise an alert.

---

## 7. Customers, dues and memberships

* **Customers** – search, add, open a profile: total visits, total spend, average session, favourite game, membership, last visit, loyalty points and **outstanding dues**.
* **Outstanding dues** tab – everyone who owes money, with a one-tap **WhatsApp reminder**. Open a customer → **Collect dues** to record a payment. *Add opening due* records old balances from the paper book.
* **Memberships** → **+ Sell membership**: pick customer, plan (e.g. *30 Hours Pack ₹3,000 / 30 days*), payment method, optionally tap an **RFID card** to link it. Hours are deducted in 30-minute blocks when the member plays; any extra time is billed normally.
  *Renew* extends validity and adds the plan's hours. *Expiring (7d)* lists members to call.

---

## 8. Cash shift and expenses

* **Start of duty:** Shift & Expenses → enter **Opening cash** → **Open shift**.
* All cash you collect is counted automatically.
* **Expenses** (grocery, general, police, salary, charity, maintenance…) – enter amount, description, paid to.
* **End of duty:** count the drawer → enter **Counted cash** → **Close shift**. The system shows *Expected* vs *Counted*; any difference is flagged to the manager (**CASH_VARIANCE**).

---

## 9. Devices and automatic detection

* Devices page shows each sensor/reader/camera as **ONLINE / OFFLINE**. If a device is offline, **just use manual Start/Stop** – billing never depends on hardware.
* The **Detection** tab shows each table's detection state and confidence. A single movement never starts billing.
* **Hardware options** tab explains the available detection methods. See `docs/HARDWARE_DETECTION.md` for full details.

---

## 10. Manager & admin tasks

* **Reports:** revenue (daily/weekly/monthly/yearly) vs expenses, table utilisation %, peak hours, games, payment methods, top customers, product sales. **Export CSV** for the accountant.
* **Approvals & Alerts:** approve/reject discount and item-cancellation requests; acknowledge alerts (device offline, spoofing, stale events, idle tables, cash variance, low stock).
* **Tables:** edit rates (base / happy-hour / peak), maintenance, print QR codes. Every price change is audited with the reason.
* **Pricing rules:** e.g. *Weekend evening peak ×1.2*, *Holiday pricing*, *Members ₹120/h*, *Monsoon promo 1–15 July ₹99/h*.
* **Settings:** billing block & rounding, tax, deposit rules, cancellation policy, hold time, no-show grace, detection thresholds, loyalty (₹100 = 1 point), reminders.
* **Users & roles:** add staff with password and/or PIN, assign role (Super Admin, Club Admin, Manager, Receptionist, Staff), disable leavers.
* **Audit log:** who changed what, when, from which IP, before → after, and why.
* **Tournaments:** create, add players, **Generate draw & start** (knockout brackets with byes, round robin, groups → knockout), enter scores; winners advance automatically; leaderboard.

---

## 11. What to do when…

| Situation | Action |
|-----------|--------|
| Internet is down | Staff screens keep the last data; start/stop needs the server. If the server is in the cloud and unreachable, note times on paper and use **Adjust** (manager) later. |
| A sensor is offline | Manual start/stop; tell the technician. |
| Customer says the bill is wrong | Open the bill, check the lines (each time segment is shown with its rate); apply a correction with a reason. |
| Customer paid online but shows as unpaid | Wait 1 minute (the payment provider confirms by webhook). If the slot was taken meanwhile the system refunds automatically and raises an alert. |
| Started the wrong table | Table → *Cancel without charge* (reason required) and start the right one. |
| Forgot to press start | Start now; a manager can **Adjust** the start time (audited). |
| "Table reserved" when starting a walk-in | Check the booking time; start another table or override with manager approval. |
