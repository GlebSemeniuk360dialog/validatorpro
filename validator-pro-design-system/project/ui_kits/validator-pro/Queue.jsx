// ui_kits/validator-pro/Queue.jsx
// Recreates render_queue: button row, search, multi-row table.
const QUEUE_ROWS = [
  { key: 'MAS-4141', summary: 'WhatsApp Chat Prospekt 17 Oct — ALDI Süd Living',           client: 'ALDI Sued',     date: '2026-10-17', status: 'In Progress' },
  { key: 'MAS-4138', summary: 'Sonntag Sendout — Kaufland RCS Wave 42',                    client: 'Kaufland RCS',  date: '2026-10-19', status: 'Open' },
  { key: 'MAS-4137', summary: 'Reminder Prospekt Familien — ALDI Süd',                     client: 'ALDI Sued',     date: '2026-10-16', status: 'Open' },
  { key: 'MAS-4135', summary: 'PENNY.Angebote — Wave 41',                                  client: 'PENNY Austria', date: '2026-10-15', status: 'Open' },
  { key: 'MAS-4132', summary: 'ALDI Portugal Northern · weekly leaflet',                   client: 'ALDI Portugal', date: '2026-10-14', status: 'In Progress' },
  { key: 'MAS-4131', summary: 'REWE · Wochenendprospekt 41/42',                            client: 'REWE',          date: '2026-10-14', status: 'Open' },
  { key: 'MAS-4128', summary: 'Penny Germany · DE Standard',                               client: 'Penny Germany', date: '2026-10-13', status: 'Open' },
  { key: 'MAS-4127', summary: 'Bauhaus · Heimwerker-Angebote Oktober',                     client: 'Bauhaus',       date: '2026-10-13', status: 'Open' },
  { key: 'MAS-4124', summary: 'TUI Belgium · Third Party FR locale',                       client: 'TUI Belgium',   date: '2026-10-12', status: 'Open' },
  { key: 'MAS-4120', summary: 'Toom · Garten und Heimwerken Sendout',                      client: 'Toom',          date: '2026-10-12', status: 'Open' },
];

function Queue({ onLoad, selected, setSelected }) {
  const [search, setSearch] = React.useState('');
  const [clientFilter, setClientFilter] = React.useState('All clients');

  const clients = ['All clients', ...new Set(QUEUE_ROWS.map(r => r.client))];

  const filtered = QUEUE_ROWS.filter(r => {
    if (clientFilter !== 'All clients' && r.client !== clientFilter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return r.key.toLowerCase().includes(q) || r.summary.toLowerCase().includes(q) ||
           r.client.toLowerCase().includes(q);
  });

  const toggle = (k) => {
    const next = new Set(selected);
    if (next.has(k)) next.delete(k); else next.add(k);
    setSelected(next);
  };

  const selectedKeys = [...selected];
  const singleSel = selectedKeys.length === 1 ? selectedKeys[0] : null;
  const multiSel  = selectedKeys.length > 1;
  const row = singleSel ? QUEUE_ROWS.find(r => r.key === singleSel) : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', gap: 12 }}>
        <Button variant="ghost">🔄 Refresh Queue</Button>
        <Input value={search} onChange={setSearch} placeholder="Type key or summary..." style={{ flex: 1 }} />
      </div>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <Select value={clientFilter} onChange={setClientFilter} options={clients} style={{ maxWidth: 260 }} />
        <div style={{ fontSize: 13, color: tokens.fg[1], fontWeight: 600 }}>Pending Tickets: {filtered.length}</div>
        <div style={{ fontSize: 12, color: tokens.fg[3] }}>Select one ticket to validate · select multiple for bulk actions</div>
      </div>

      <div style={{
        background: tokens.bg.surface1, border: `1px solid ${tokens.border.base}`,
        borderRadius:6, overflow: 'hidden',
      }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '40px 100px 1fr 170px 130px 110px',
          padding: '12px 14px', gap: 12, borderBottom: `1px solid ${tokens.border.base}`,
          fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.08em',
          color: tokens.fg[3],
        }}>
          <div></div>
          <div>ID</div>
          <div>Summary</div>
          <div>Client</div>
          <div>Sendout Date</div>
          <div>Status</div>
        </div>
        {filtered.map(r => {
          const isSel = selected.has(r.key);
          return (
            <div key={r.key}
              onClick={() => toggle(r.key)}
              style={{
                display: 'grid', gridTemplateColumns: '40px 100px 1fr 170px 130px 110px',
                padding: '12px 14px', gap: 12,
                borderBottom: `1px solid ${tokens.border.base}`,
                fontSize: 13, color: tokens.fg[1],
                background: isSel ? tokens.brand.soft : 'transparent',
                cursor: 'pointer',
              }}>
              <div style={{ color: isSel ? tokens.brand.text : tokens.fg[4] }}>
                <input type="checkbox" checked={isSel} readOnly />
              </div>
              <div style={{ fontFamily: tokens.font.mono, fontSize: 12, color: tokens.fg[1] }}>{r.key}</div>
              <div style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{r.summary}</div>
              <div style={{ color: tokens.fg[2] }}>{r.client}</div>
              <div style={{ fontFamily: tokens.font.mono, fontSize: 12, color: tokens.fg[2] }}>{r.date}</div>
              <div>
                <span style={{
                  fontSize: 11, fontFamily: tokens.font.sans, padding: '3px 10px', borderRadius:999,
                  background: r.status === 'In Progress' ? tokens.warn.soft : tokens.info.soft,
                  color: r.status === 'In Progress' ? tokens.warn.base : tokens.brand.text,
                  border: `1px solid ${r.status === 'In Progress' ? tokens.warn.ring : tokens.info.ring}`,
                }}>{r.status}</span>
              </div>
            </div>
          );
        })}
      </div>

      {singleSel && (
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <div style={{
            flex: 1, padding: '10px 14px', borderRadius:4,
            background: tokens.info.soft, border: `1px solid ${tokens.info.ring}`,
            color: tokens.brand.text, fontSize: 13,
          }}><strong>{singleSel}</strong> — ready to validate</div>
          <Button onClick={() => onLoad(row)}>▶ Load ticket</Button>
        </div>
      )}
      {multiSel && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{
            padding: '10px 14px', borderRadius:4,
            background: tokens.info.soft, border: `1px solid ${tokens.info.ring}`,
            color: tokens.brand.text, fontSize: 13,
          }}><strong>{selectedKeys.length} tickets selected:</strong> {selectedKeys.join(', ')}</div>
          <div style={{ display: 'flex', gap: 12 }}>
            <Button>⚡ Regular Bulk Check</Button>
            <Button variant="ghost">🤖 AI Bulk Audit</Button>
            <Button variant="ghost" onClick={() => setSelected(new Set())}>✕ Clear selection</Button>
          </div>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { Queue, QUEUE_ROWS });
