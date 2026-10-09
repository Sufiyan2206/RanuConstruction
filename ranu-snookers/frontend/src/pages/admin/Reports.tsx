import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { API_BASE, get, tokenStore } from "@/services/api";
import { useBranchId } from "@/hooks/useBranch";
import { Card, CardTitle, DataTable, Field, Input, Select, Stat, Td, Button } from "@/components/ui";
import { money, num, todayLocal } from "@/lib/format";

const axis = { stroke: "#7b756b", fontSize: 11 };
const tip = { contentStyle: { background: "#ffffff", border: "1px solid #ebe4d6", borderRadius: 12, color: "#17140f", boxShadow: "0 8px 24px -12px rgba(23,20,15,.2)" } };

export default function Reports() {
  const branchId = useBranchId();
  const [from, setFrom] = useState(todayLocal(-29));
  const [to, setTo] = useState(todayLocal());
  const [period, setPeriod] = useState("daily");
  const range = { from, to };
  const enabled = !!branchId;
  const rev = useQuery({ queryKey: ["r-rev", branchId, from, to, period], queryFn: () => get<any>(`/branches/${branchId}/reports/revenue`, { ...range, period }), enabled });
  const util = useQuery({ queryKey: ["r-util", branchId, from, to], queryFn: () => get<any[]>(`/branches/${branchId}/reports/utilization`, range), enabled });
  const peak = useQuery({ queryKey: ["r-peak", branchId, from, to], queryFn: () => get<any[]>(`/branches/${branchId}/reports/peak-hours`, range), enabled });
  const games = useQuery({ queryKey: ["r-games", branchId, from, to], queryFn: () => get<any[]>(`/branches/${branchId}/reports/games`, range), enabled });
  const pay = useQuery({ queryKey: ["r-pay", branchId, from, to], queryFn: () => get<any[]>(`/branches/${branchId}/reports/payments`, range), enabled });
  const cust = useQuery({ queryKey: ["r-cust", branchId, from, to], queryFn: () => get<any>(`/branches/${branchId}/reports/customers`, range), enabled });
  const prod = useQuery({ queryKey: ["r-prod", branchId, from, to], queryFn: () => get<any[]>(`/branches/${branchId}/reports/products`, range), enabled });

  const exportCsv = async () => {
    const r = await fetch(`${API_BASE}/branches/${branchId}/reports/revenue.csv?from=${from}&to=${to}&period=${period}`, { headers: { Authorization: `Bearer ${tokenStore.get()}` } });
    const url = URL.createObjectURL(await r.blob());
    Object.assign(document.createElement("a"), { href: url, download: `revenue_${from}_${to}.csv` }).click();
    URL.revokeObjectURL(url);
  };
  const series = (rev.data?.series ?? []).map((s: any) => ({ ...s, collected: num(s.collected), expenses: num(s.expenses) }));
  const peakData = (peak.data ?? []).filter((p: any) => p.table_minutes > 0 || (p.hour >= 10 || p.hour < 3));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold">Reports</h1>
        <div className="flex flex-wrap items-end gap-2">
          <Field label="From"><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="To"><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          <Field label="Group"><Select value={period} onChange={(e) => setPeriod(e.target.value)}><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="yearly">Yearly</option></Select></Field>
          <Button variant="secondary" onClick={exportCsv}>Export CSV</Button>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Collected" value={money(rev.data?.total_collected)} tone="good" />
        <Stat label="Expenses" value={money(rev.data?.total_expenses)} />
        <Stat label="Net" value={money(rev.data?.net)} tone={num(rev.data?.net) >= 0 ? "good" : "bad"} />
        <Stat label="New customers" value={cust.data?.new_customers ?? "—"} sub={cust.data ? `${cust.data.returning_customers} returning · ${cust.data.members_visiting} members` : undefined} />
      </div>
      <Card>
        <CardTitle>Revenue vs expenses</CardTitle>
        <div className="h-64">
          <ResponsiveContainer>
            <BarChart data={series}><CartesianGrid stroke="#ebe4d6" vertical={false} /><XAxis dataKey="period" {...axis} /><YAxis {...axis} /><Tooltip {...tip} formatter={(v) => money(v as number)} />
              <Bar dataKey="collected" name="Collected" fill="#17140f" radius={[4, 4, 0, 0]} /><Bar dataKey="expenses" name="Expenses" fill="#c9a24b" radius={[4, 4, 0, 0]} /></BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle>Peak hours (table-minutes)</CardTitle>
          <div className="h-56"><ResponsiveContainer><BarChart data={peakData}><XAxis dataKey="label" {...axis} /><YAxis {...axis} /><Tooltip {...tip} /><Bar dataKey="table_minutes" name="Minutes" fill="#c9a24b" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div>
        </Card>
        <Card>
          <CardTitle>Table utilisation</CardTitle>
          <div className="space-y-1.5">
            {(util.data ?? []).map((u: any) => (
              <div key={u.table_id} className="flex items-center gap-2 text-sm"><span className="w-20 shrink-0">{u.name}</span>
                <div className="h-3 flex-1 rounded-full bg-surface-2"><div className="h-3 rounded-full bg-gradient-to-r from-brass-500 to-[#b48d38]" style={{ width: `${Math.min(100, u.utilization_percent)}%` }} /></div>
                <span className="num w-14 text-right">{u.utilization_percent}%</span></div>
            ))}
          </div>
        </Card>
        <Card className="p-0 sm:p-0">
          <div className="p-4 pb-0 font-semibold">Games</div>
          <DataTable head={["Game", "Sessions", "Hours", "Billed"]}>{(games.data ?? []).map((g: any) => <tr key={g.game}><Td>{g.game}</Td><Td>{g.sessions}</Td><Td>{g.hours}</Td><Td className="num">{money(g.billed)}</Td></tr>)}</DataTable>
        </Card>
        <Card className="p-0 sm:p-0">
          <div className="p-4 pb-0 font-semibold">Payment methods</div>
          <DataTable head={["Method", "Amount"]}>{(pay.data ?? []).map((p: any) => <tr key={p.method}><Td>{p.method}</Td><Td className="num">{money(p.amount)}</Td></tr>)}</DataTable>
        </Card>
        <Card className="p-0 sm:p-0">
          <div className="p-4 pb-0 font-semibold">Top customers</div>
          <DataTable head={["Customer", "Phone", "Bills", "Spend"]}>{(cust.data?.top_customers ?? []).map((c: any) => <tr key={c.customer_id}><Td>{c.name}</Td><Td>{c.phone}</Td><Td>{c.invoices}</Td><Td className="num">{money(c.spend)}</Td></tr>)}</DataTable>
        </Card>
        <Card className="p-0 sm:p-0">
          <div className="p-4 pb-0 font-semibold">Food, drinks &amp; accessories</div>
          <DataTable head={["Product", "Qty", "Amount"]}>{(prod.data ?? []).map((p: any) => <tr key={p.product}><Td>{p.product}</Td><Td>{p.quantity}</Td><Td className="num">{money(p.amount)}</Td></tr>)}</DataTable>
        </Card>
      </div>
    </div>
  );
}
