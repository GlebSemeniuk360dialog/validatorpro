// ui_kits/validator-pro/OrphanScanner.jsx
// Mirrors render_orphan_scanner + _render_orphan_results.
const ORPHANS = [
  { status: 'no_jira',   date: '2026-10-18', client: 'ALDI Sued',     name: 'Reminder Living Sonntag',                id: '7c1f-aaaa-bbbb-1234' },
  { status: 'no_jira',   date: '2026-10-20', client: 'Kaufland WABA', name: 'Spontaneous Wave 42',                    id: 'd281-eeee-ffff-9876' },
  { status: 'no_gsheet', date: '2026-10-19', client: 'REWE',          name: 'Wochenendprospekt 41 (extra wave)',      id: '99aa-1234-5678-cccc' },
  { status: 'auto',      date: '2026-10-21', client: 'Migros',        name: 'DE Sendout · CH locale=de',              id: '4f4f-2222-3333-aaaa' },
  { status: 'auto',      date: '2026-10-21', client: 'Wreesmann',     name: 'Regular Sendout',                        id: '1111-2222-3333-4444' },
];

function OrphanScanner() {
  const [scanned, setScanned] = React.useState(true);
  const orphans = ORPHANS.filter(r => r.status === 'no_jira' || r.status === 'no_gsheet');
  const auto    = ORPHANS.filter(r => r.status === 'auto');

  if (!scanned) {
    return (
      <div style={{ padding: 24 }}>
        <SectionHeader style={{ marginTop: 0 }}>⚠️ Orphan Sendout Scanner</SectionHeader>
        <div style={{ fontSize: 13, color: tokens.fg[3], lineHeight: 1.7, marginBottom: 16 }}>
          Finds DMA sendouts that have no matching JIRA ticket in the queue or G-Sheet row.
          These may be manually created sendouts, duplicates, or forgotten configurations.
        </div>
        <Button onClick={() => setScanned(true)}>Scan all accounts</Button>
      </div>
    );
  }

  return (
    <div>
      <SectionHeader style={{ marginTop: 0 }}>⚠️ Orphan Sendout Scanner</SectionHeader>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 14 }}>
        <Metric label="Total sendouts"    value={ORPHANS.length} />
        <Metric label="✅ Matched"         value={ORPHANS.length - orphans.length - auto.length} kind="ok" />
        <Metric label="⚠️ Untracked"       value={orphans.length} kind="danger" />
      </div>
      <Badge kind="info">🔵 {auto.length} automated sendout(s) excluded from orphan check (no JIRA required).</Badge>

      <Group icon="🔴" label="Missing from JIRA queue"     rows={ORPHANS.filter(r => r.status === 'no_jira')}   defaultOpen />
      <Group icon="🟡" label="Missing from G-Sheet"        rows={ORPHANS.filter(r => r.status === 'no_gsheet')} />
      <Group icon="🔵" label="Automated (no JIRA required)" rows={auto}                                          collapsed />
    </div>
  );
}

function Group({ icon, label, rows, defaultOpen, collapsed }) {
  const [open, setOpen] = React.useState(defaultOpen || (!collapsed && rows.length <= 2));
  if (rows.length === 0) return null;
  return (
    <div style={{ marginTop: 22 }}>
      <div onClick={() => setOpen(o => !o)} style={{
        fontSize: 14, fontWeight: 600, color: tokens.fg[1],
        cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10,
      }}>
        <span style={{ fontSize: 14 }}>{icon}</span>{label} <span style={{ color: tokens.fg[3], fontWeight: 400 }}>({rows.length})</span>
      </div>
      {open && rows.map((r, i) => (
        <div key={i} style={{
          background: tokens.bg.surface1, border: `1px solid ${tokens.border.base}`,
          borderRadius:6, padding: '14px 18px', marginBottom: 10,
        }}>
          <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ fontFamily: tokens.font.mono, fontSize: 12, color: tokens.fg[2] }}>{r.date}</div>
            <div style={{ fontSize: 13, color: tokens.fg[1], fontWeight: 600 }}>{r.client}</div>
            <div style={{ fontSize: 13, color: tokens.fg[2], flex: 1 }}>{r.name}</div>
            <code style={{
              fontFamily: tokens.font.mono, background: tokens.bg.surface3,
              padding: '2px 8px', borderRadius: 3, fontSize: 11, color: tokens.fg[2],
            }}>{r.id}</code>
            <Badge kind={r.status === 'no_jira' ? 'danger' : r.status === 'no_gsheet' ? 'warn' : 'info'}>
              {r.status === 'no_jira' ? '❌ JIRA' : r.status === 'no_gsheet' ? '❌ G-Sheet' : 'Auto'}
            </Badge>
          </div>
          {r.status === 'no_jira' && (
            <div style={{
              marginTop: 10, padding: '10px 14px', borderRadius:4,
              background: tokens.warn.soft2, border: `1px solid ${tokens.warn.soft}`,
              color: tokens.fg[1], fontSize: 12, lineHeight: 1.6,
            }}>
              ⚠️ This sendout has no matching JIRA ticket. It may have been created directly in DMA without going through the approval process.
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

Object.assign(window, { OrphanScanner });
