import { lazy, Suspense } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/stores/auth";
import { Spinner, ToastProvider } from "@/components/ui";
import { PublicLayout } from "@/layouts/PublicLayout";
import { AdminLayout } from "@/layouts/AdminLayout";
import Home from "@/pages/public/Home";
import { ApiError } from "@/services/api";

const Book = lazy(() => import("@/pages/public/Book"));
const BookingStatus = lazy(() => import("@/pages/public/BookingStatus"));
const Login = lazy(() => import("@/pages/public/Auth").then((m) => ({ default: m.Login })));
const Register = lazy(() => import("@/pages/public/Auth").then((m) => ({ default: m.Register })));
const MyBookings = lazy(() => import("@/pages/public/Customer").then((m) => ({ default: m.MyBookings })));
const QrStart = lazy(() => import("@/pages/public/Customer").then((m) => ({ default: m.QrStart })));
const Dashboard = lazy(() => import("@/pages/admin/Dashboard"));
const Tables = lazy(() => import("@/pages/admin/Tables"));
const Bookings = lazy(() => import("@/pages/admin/Bookings"));
const Billing = lazy(() => import("@/pages/admin/Billing"));
const Pos = lazy(() => import("@/pages/admin/Billing").then((m) => ({ default: m.Pos })));
const Customers = lazy(() => import("@/pages/admin/Customers"));
const Memberships = lazy(() => import("@/pages/admin/Customers").then((m) => ({ default: m.Memberships })));
const Inventory = lazy(() => import("@/pages/admin/Operations").then((m) => ({ default: m.Inventory })));
const ShiftExpenses = lazy(() => import("@/pages/admin/Operations").then((m) => ({ default: m.ShiftExpenses })));
const ApprovalsAlerts = lazy(() => import("@/pages/admin/Operations").then((m) => ({ default: m.ApprovalsAlerts })));
const Devices = lazy(() => import("@/pages/admin/Devices"));
const Reports = lazy(() => import("@/pages/admin/Reports"));
const Settings = lazy(() => import("@/pages/admin/Admin").then((m) => ({ default: m.Settings })));
const Users = lazy(() => import("@/pages/admin/Admin").then((m) => ({ default: m.Users })));
const Audit = lazy(() => import("@/pages/admin/Admin").then((m) => ({ default: m.Audit })));
const Tournaments = lazy(() => import("@/pages/admin/Admin").then((m) => ({ default: m.Tournaments })));

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      refetchOnWindowFocus: true,
      retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
    },
  },
});

function NotFound() {
  return <div className="p-16 text-center text-ink-400">Page not found.</div>;
}

export function AppRoutes() {
  return (
    <Suspense fallback={<div className="grid h-64 place-items-center"><Spinner /></div>}>
      <Routes>
        <Route element={<PublicLayout />}>
          <Route index element={<Home />} />
          <Route path="book" element={<Book />} />
          <Route path="booking/:reference" element={<BookingStatus />} />
          <Route path="login" element={<Login />} />
          <Route path="register" element={<Register />} />
          <Route path="my/bookings" element={<MyBookings />} />
          <Route path="t/:token" element={<QrStart />} />
        </Route>
        <Route path="admin" element={<AdminLayout />}>
          <Route index element={<Dashboard />} />
          <Route path="tables" element={<Tables />} />
          <Route path="bookings" element={<Bookings />} />
          <Route path="billing" element={<Billing />} />
          <Route path="pos" element={<Pos />} />
          <Route path="customers" element={<Customers />} />
          <Route path="memberships" element={<Memberships />} />
          <Route path="inventory" element={<Inventory />} />
          <Route path="shift" element={<ShiftExpenses />} />
          <Route path="devices" element={<Devices />} />
          <Route path="tournaments" element={<Tournaments />} />
          <Route path="reports" element={<Reports />} />
          <Route path="approvals" element={<ApprovalsAlerts />} />
          <Route path="settings" element={<Settings />} />
          <Route path="users" element={<Users />} />
          <Route path="audit" element={<Audit />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
