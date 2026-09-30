import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('../src/lib/months.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
const { shipmentMonth, formatMonth, monthlyOverview } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

const rows = [
 { id: 'old', shipped: '2026-09-10', arrived: '' },
 { id: 'onboarding', month: '2026-10', shipped: '2026-09-28', arrived: '2026-09-30' },
 { id: 'october', month: '', shipped: '2026-10-02', arrived: '' },
 { id: 'new-year', month: '2027-01', shipped: '2026-12-28', arrived: '' },
];

test('legacy entries use shipping month; onboarding assignment overrides shipping and arrival', () => {
 assert.equal(shipmentMonth(rows[0]), '2026-09');
 assert.equal(shipmentMonth(rows[1]), '2026-10');
 assert.equal(shipmentMonth(rows[2]), '2026-10');
 assert.equal(formatMonth('2026-10'), 'Oktober 2026');
});

test('month and status filters agree with counts and keep empty months selectable', () => {
 const overview = monthlyOverview(rows, '2026-10', 'arrived');
 assert.deepEqual([overview.total, overview.underway, overview.arrived, overview.count], [2, 1, 1, 1]);
 assert.deepEqual(overview.groups[0].items.map(row => row.id), ['onboarding']);
 const empty = monthlyOverview(rows, '2026-11', 'all');
 assert.equal(empty.total, 0);
 assert.deepEqual(empty.groups, []);
});

test('all months sort newest first across years and sort shipments within each month', () => {
 const snapshot = JSON.stringify(rows);
 const overview = monthlyOverview(rows, 'all', 'all');
 assert.deepEqual(overview.groups.map(group => group.month), ['2027-01', '2026-10', '2026-09']);
 assert.deepEqual(overview.groups[1].items.map(row => row.id), ['october', 'onboarding']);
 assert.equal(JSON.stringify(rows), snapshot);
 assert.equal(monthlyOverview(rows, 'all', 'open').count, 3);
});
