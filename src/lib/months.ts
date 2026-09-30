type MonthlyShipment = { month?: string; shipped: string; arrived: string };

export const shipmentMonth = (row: MonthlyShipment) => row.month || row.shipped.slice(0, 7);
export const formatMonth = (month: string) => new Intl.DateTimeFormat('de-DE', {
 month: 'long', year: 'numeric',
}).format(new Date(`${month}-01T12:00:00`));

export function monthlyOverview<T extends MonthlyShipment>(rows: T[], month: string, status: string) {
 const scoped = rows.filter(row => month === 'all' || shipmentMonth(row) === month);
 const underway = scoped.filter(row => !row.arrived).length;
 const visible = scoped.filter(row => status === 'all' || (status === 'open' ? !row.arrived : !!row.arrived));
 const groups = new Map<string, T[]>();
 for (const row of visible) {
  const key = shipmentMonth(row);
  const group = groups.get(key) || [];
  group.push(row);
  groups.set(key, group);
 }
 return {
  total: scoped.length, underway, arrived: scoped.length - underway, count: visible.length,
  groups: [...groups.entries()].sort(([a], [b]) => b.localeCompare(a))
   .map(([key, items]) => ({ month: key, items: [...items].sort((a, b) => b.shipped.localeCompare(a.shipped)) })),
 };
}
