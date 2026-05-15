// ui_kits/validator-pro/Shell.jsx
// Top-level app chrome — sidebar + main content. Mirrors Streamlit's
// layout="wide" with the dark-theme CSS injected on top.
const { useState: useStateShell } = React;

function Topbar({ title }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '14px 28px',
      background: tokens.bg.app,
      borderBottom: `1px solid ${tokens.border.base}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <img src="../../assets/validator-mark.svg" alt="360dialog" style={{
          width: 36, height: 36, borderRadius: 4, display: 'block',
        }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div style={{
            fontFamily: tokens.font.display, fontSize: 18, fontWeight: 600,
            color: tokens.fg[1], letterSpacing: '-0.01em',
          }}>{title}</div>
          <div style={{
            fontFamily: tokens.font.mono, fontSize: 10,
            letterSpacing: '0.16em', textTransform: 'uppercase',
            color: tokens.brand.text,
          }}>360DIALOG · OPS · v1.0</div>
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: tokens.font.mono, fontSize: 11, color: tokens.fg[3] }}>
          <Led kind="ok" pulse />
          <span>360dialog.atlassian.net</span>
        </div>
        <div style={{ fontFamily: tokens.font.mono, fontSize: 11, color: tokens.fg[4] }}>
          {new Date().toISOString().slice(11, 19)}
        </div>
      </div>
    </div>
  );
}

function Sidebar({ user, onSignOut, onRefreshSheet, onClearCache }) {
  return (
    <aside style={{
      width: 260, flexShrink: 0,
      background: tokens.bg.surface1,
      borderRight: `1px solid ${tokens.border.base}`,
      padding: 18,
      display: 'flex', flexDirection: 'column', gap: 14,
      minHeight: '100vh',
      fontFamily: tokens.font.sans, fontSize: 13, color: tokens.fg[2],
    }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Led kind="ok" pulse />
          <div style={{ fontWeight: 600, color: tokens.fg[1] }}>{user}</div>
        </div>
        <Button variant="ghost" onClick={onSignOut}>Sign out</Button>
      </div>

      <hr style={{ border: 'none', borderTop: `1px dashed ${tokens.border.hud}`, margin: '4px 0' }} />

      {/* Connection rail — futurist sidebar staple */}
      <Overline style={{ marginBottom: -4 }}>— connections</Overline>
      <ConnRow led="ok"     label="DMA API"        meta="200" />
      <ConnRow led="ok"     label="JIRA"           meta="200" />
      <ConnRow led="warn"   label="G-Sheet"        meta="stale 4m" />
      <ConnRow led="dim"    label="Slack webhook"  meta="idle" />

      <hr style={{ border: 'none', borderTop: `1px dashed ${tokens.border.hud}`, margin: '4px 0' }} />

      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: tokens.fg[2] }}>
        <input type="checkbox" /> JIRA Field Inspector
      </label>
      <Button variant="ghost" onClick={onRefreshSheet}>🔄 Refresh G-Sheet</Button>
      <Button variant="ghost" onClick={onClearCache}>Clear Cache</Button>

      <div style={{ marginTop: 'auto', fontFamily: tokens.font.mono, fontSize: 10, color: tokens.fg[4], lineHeight: 1.7, letterSpacing: '0.08em' }}>
        SESSION&nbsp;·&nbsp;<span style={{ color: tokens.accent.base }}>{Math.floor(Math.random()*900 + 100)}.7s</span><br/>
        BUILD&nbsp;·&nbsp;<span style={{ color: tokens.fg[3] }}>2026.05.14-stable</span>
      </div>
    </aside>
  );
}

function ConnRow({ led, label, meta }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      fontFamily: tokens.font.mono, fontSize: 11,
      color: tokens.fg[3], letterSpacing: '0.04em',
    }}>
      <Led kind={led} pulse={led === 'ok' || led === 'warn'} />
      <span style={{ textTransform: 'uppercase' }}>{label}</span>
      <span style={{ marginLeft: 'auto', color: tokens.fg[4] }}>{meta}</span>
    </div>
  );
}

function MainTabs({ active, onChange }) {
  // Top-level tabs: Validator · Orphan Scanner · Dashboard (from app.py:2513)
  const tabs = ['Validator', 'Orphan Scanner', 'Dashboard'];
  return (
    <div style={{
      position: 'sticky', top: 0, zIndex: 99, background: tokens.bg.app,
      borderBottom: `1px solid ${tokens.border.base}`, padding: '8px 28px',
    }}>
      <div style={{
        display: 'flex', gap: 4, background: tokens.bg.surface1,
        border: `1px solid ${tokens.border.base}`, borderRadius:8, padding: 5,
        maxWidth: 600,
      }}>
        {tabs.map(t => (
          <NavPill key={t} active={active === t} onClick={() => onChange(t)}>{t}</NavPill>
        ))}
      </div>
    </div>
  );
}

function NavPill({ active, onClick, children }) {
  const [hover, setHover] = useStateShell(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        flex: 1, padding: '9px 12px',
        background: active ? tokens.brand.base : (hover ? tokens.bg.surface3 : 'transparent'),
        color: active ? '#fff' : (hover ? tokens.fg[1] : tokens.fg[3]),
        borderRadius:4, cursor: 'pointer', userSelect: 'none',
        fontFamily: tokens.font.sans, fontSize: 13, fontWeight: 500,
        transition: 'all .18s', whiteSpace: 'nowrap', textAlign: 'center',
      }}
    >{children}</div>
  );
}

Object.assign(window, { Topbar, Sidebar, MainTabs, NavPill });
