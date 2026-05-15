// src/mobile-data.jsx — hardcoded fixture data shared by all screens.

const QUEUE_ROWS = [
  { key: 'MAS-4141', summary: 'WhatsApp Chat Prospekt 17 Oct — ALDI Süd Living', client: 'ALDI Sued',     date: '2026-10-17', status: 'In Progress', priority: 'high' },
  { key: 'MAS-4138', summary: 'Sonntag Sendout — Kaufland RCS Wave 42',          client: 'Kaufland RCS',  date: '2026-10-19', status: 'Open',        priority: 'med' },
  { key: 'MAS-4137', summary: 'Reminder Prospekt Familien — ALDI Süd',           client: 'ALDI Sued',     date: '2026-10-16', status: 'Open',        priority: 'high' },
  { key: 'MAS-4135', summary: 'PENNY.Angebote — Wave 41',                        client: 'PENNY Austria', date: '2026-10-15', status: 'Open',        priority: 'med' },
  { key: 'MAS-4132', summary: 'ALDI Portugal Northern · weekly leaflet',         client: 'ALDI Portugal', date: '2026-10-14', status: 'In Progress', priority: 'low' },
  { key: 'MAS-4131', summary: 'REWE · Wochenendprospekt 41/42',                  client: 'REWE',          date: '2026-10-14', status: 'Open',        priority: 'med' },
  { key: 'MAS-4128', summary: 'Penny Germany · DE Standard',                     client: 'Penny Germany', date: '2026-10-13', status: 'Open',        priority: 'low' },
  { key: 'MAS-4127', summary: 'Bauhaus · Heimwerker-Angebote Oktober',           client: 'Bauhaus',       date: '2026-10-13', status: 'Open',        priority: 'low' },
  { key: 'MAS-4124', summary: 'TUI Belgium · Third Party FR locale',             client: 'TUI Belgium',   date: '2026-10-12', status: 'Open',        priority: 'med' },
];

const ORPHANS = [
  { status: 'no_jira',   date: '2026-10-18', client: 'ALDI Sued',     name: 'Reminder Living Sonntag',           id: '7c1f-aaaa-bbbb-1234' },
  { status: 'no_jira',   date: '2026-10-20', client: 'Kaufland WABA', name: 'Spontaneous Wave 42',               id: 'd281-eeee-ffff-9876' },
  { status: 'no_gsheet', date: '2026-10-19', client: 'REWE',          name: 'Wochenendprospekt 41 (extra wave)', id: '99aa-1234-5678-cccc' },
  { status: 'auto',      date: '2026-10-21', client: 'Migros',        name: 'DE Sendout · CH locale=de',         id: '4f4f-2222-3333-aaaa' },
  { status: 'auto',      date: '2026-10-21', client: 'Wreesmann',     name: 'Regular Sendout',                   id: '1111-2222-3333-4444' },
];

const LOG = [
  { ts: '14:42', user: 'gleb',    action: 'VALIDATE',     detail: 'MAS-4141 · ALDI Sued · 0 issues',         kind: 'ok' },
  { ts: '14:38', user: 'gleb',    action: 'AI_AUDIT',     detail: 'MAS-4141 · 2 issues found',               kind: 'danger' },
  { ts: '14:31', user: 'martina', action: 'SLACK_ALERT',  detail: 'MAS-4138 · sent to #ops',                 kind: 'warn' },
  { ts: '14:29', user: 'martina', action: 'AI_AUDIT',     detail: 'MAS-4138 · 1 issue found',                kind: 'warn' },
  { ts: '14:12', user: 'alex',    action: 'BULK_VALIDATE',detail: '4 tickets · all passed',                  kind: 'ok' },
  { ts: '13:58', user: 'alex',    action: 'JIRA_APPROVE', detail: 'MAS-4124 · TUI Belgium',                  kind: 'ok' },
  { ts: '13:46', user: 'gleb',    action: 'LOGIN',        detail: '',                                        kind: 'info' },
];

const CONNECTIONS = [
  { led: 'ok',   label: 'DMA API',       meta: '200' },
  { led: 'ok',   label: 'JIRA',          meta: '200' },
  { led: 'warn', label: 'G-Sheet',       meta: 'stale 4m' },
  { led: 'dim',  label: 'Slack webhook', meta: 'idle' },
];

// Compute days until sendout for the queue rows
function daysUntil(dateStr) {
  // Use a fixed "today" so the prototype always shows the same countdowns
  const today = new Date('2026-10-13T09:00:00Z');
  const d = new Date(dateStr + 'T00:00:00Z');
  const diff = Math.round((d - today) / (1000 * 60 * 60 * 24));
  return diff;
}

Object.assign(window, { QUEUE_ROWS, ORPHANS, LOG, CONNECTIONS, daysUntil });
