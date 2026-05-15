// ui_kits/validator-pro/Dashboard.jsx
// Recap-style stats + recent validation log. There's no first-class
// dashboard layout in the codebase — just record_validation in features.py
// and st.metric blocks. We give it a clean, consistent surface here.
const LOG = [
  { ts: '14:42', user: 'gleb',    action: 'VALIDATE',     detail: 'MAS-4141 · ALDI Sued · 0 issues' ,           kind: 'ok' },
  { ts: '14:38', user: 'gleb',    action: 'AI_AUDIT',     detail: 'MAS-4141 · ALDI Sued · 2 issues found',      kind: 'danger' },
  { ts: '14:31', user: 'martina', action: 'SLACK_ALERT',  detail: 'MAS-4138 · Kaufland RCS · sent to #ops',     kind: 'warn' },
  { ts: '14:29', user: 'martina', action: 'AI_AUDIT',     detail: 'MAS-4138 · Kaufland RCS · 1 issue found',    kind: 'warn' },
  { ts: '14:12', user: 'alex',    action: 'BULK_VALIDATE', detail: '4 tickets · all passed',                    kind: 'ok' },
  { ts: '13:58', user: 'alex',    action: 'JIRA_APPROVE', detail: 'MAS-4124 · TUI Belgium',                     kind: 'ok' },
  { ts: '13:46', user: 'gleb',    action: 'LOGIN',        detail: '',                                           kind: 'info' },
];

function Dashboard() {
  return (
    <div>
      <SectionHeader style={{ marginTop: 0 }}>Today</SectionHeader>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12,
        background: tokens.bg.surface1, border: `1px solid ${tokens.border.base}`,
        borderRadius: 6, padding: '18px 22px',
      }}>
        <Readout label="Validations" value={<span>24</span>}            sub="▲ +6 vs yesterday" subKind="ok" />
        <Readout label="Pass rate"   value={<span>83%</span>} valueKind="ok"     sub="20 / 24" />
        <Readout label="Avg audit"   value={<span>2.4<span style={{color:tokens.fg[3], fontSize: 11}}>s</span></span>} valueKind="accent" sub="gemini-2.5-pro" subKind="accent" />
        <Readout label="Alerts fired" value={<span>03</span>} valueKind="danger" sub="▼ last 1h" subKind="danger" />
      </div>

      <SectionHeader>Last 7 days</SectionHeader>
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 14 }}>
        <Card title="Audit log">
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {LOG.map((l, i) => (
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '60px 80px 130px 1fr',
                gap: 12, padding: '8px 0', borderBottom: i === LOG.length - 1 ? 'none' : `1px solid ${tokens.border.base}`,
                fontSize: 12,
              }}>
                <span style={{ fontFamily: tokens.font.mono, color: tokens.fg[3] }}>{l.ts}</span>
                <span style={{ color: tokens.fg[2] }}>{l.user}</span>
                <span style={{ fontFamily: tokens.font.mono, color: tokens.fg[1] }}>{l.action}</span>
                <span style={{ color: tokens.fg[2] }}>
                  {l.kind === 'ok'     && <span style={{ color: tokens.ok.base, marginRight: 6 }}>●</span>}
                  {l.kind === 'danger' && <span style={{ color: tokens.danger.base, marginRight: 6 }}>●</span>}
                  {l.kind === 'warn'   && <span style={{ color: tokens.warn.base, marginRight: 6 }}>●</span>}
                  {l.kind === 'info'   && <span style={{ color: tokens.brand.text, marginRight: 6 }}>●</span>}
                  {l.detail}
                </span>
              </div>
            ))}
          </div>
        </Card>
        <Card title="Top failure modes">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <FailureRow label="CTA button mismatch"   count={9} />
            <FailureRow label="Footer text missing"   count={5} />
            <FailureRow label="URL placeholder unfilled" count={4} />
            <FailureRow label="Carousel slide order"  count={2} />
            <FailureRow label="Wrong leaflet_type tag" count={2} />
          </div>
        </Card>
      </div>
    </div>
  );
}

function FailureRow({ label, count }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12 }}>
      <span style={{ color: tokens.fg[2] }}>{label}</span>
      <span style={{ fontFamily: tokens.font.mono, color: tokens.danger.base, fontWeight: 600 }}>{count}</span>
    </div>
  );
}

Object.assign(window, { Dashboard });
