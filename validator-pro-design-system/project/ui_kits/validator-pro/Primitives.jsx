// ui_kits/validator-pro/Primitives.jsx
// Tiny building blocks shared by every screen.
const { useState } = React;

// Overline / section header — the system's primary hierarchy device.
// v2: mono family, wider tracking, light weight 500 reads as more technical.
function Overline({ children, style }) {
  return (
    <div style={{
      fontFamily: tokens.font.mono,
      fontSize: 11, fontWeight: 500, textTransform: 'uppercase',
      letterSpacing: tokens.ls.overline, color: tokens.fg[3], ...style,
    }}>{children}</div>
  );
}

function SectionHeader({ children, style }) {
  return (
    <div style={{
      fontFamily: tokens.font.mono,
      fontSize: 11, fontWeight: 500, textTransform: 'uppercase',
      letterSpacing: tokens.ls.overlineLoose, color: tokens.fg[3],
      margin: '28px 0 12px', paddingBottom: 8,
      borderBottom: `1px solid ${tokens.border.base}`,
      display: 'flex', alignItems: 'center', gap: 10,
      ...style,
    }}>
      <span style={{ color: tokens.accent.base, letterSpacing: 0 }}>—</span>
      <span>{children}</span>
    </div>
  );
}

// LED — 8px dot with colored glow. `pulse` = subtle live indicator.
function Led({ kind = 'accent', pulse, style }) {
  const colorMap = {
    accent: { c: tokens.accent.base, g: tokens.accent.glow },
    ok:     { c: tokens.ok.base,     g: tokens.ok.glow },
    danger: { c: tokens.danger.base, g: tokens.danger.glow },
    warn:   { c: tokens.warn.base,   g: tokens.warn.glow },
    dim:    { c: tokens.fg[4],       g: 'none' },
  };
  const { c, g } = colorMap[kind] || colorMap.accent;
  return (
    <span style={{
      display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
      background: c, boxShadow: g, verticalAlign: 'middle',
      animation: pulse ? 'vp-led-pulse 1.6s ease-in-out infinite' : 'none',
      ...style,
    }} />
  );
}

// HUD panel — adds 4 cyan L-bracket corners. Reserve for the active record.
function HudPanel({ children, style }) {
  const brackets = (pos) => {
    const base = { content: '""', position: 'absolute', width: 14, height: 14, border: `1px solid ${tokens.accent.base}`, pointerEvents: 'none' };
    return base; // not actually used — we render real spans below
  };
  return (
    <div style={{
      position: 'relative',
      background: tokens.bg.surface1,
      border: `1px solid ${tokens.border.base}`,
      borderRadius: 6, padding: '18px 22px',
      ...style,
    }}>
      <Corner style={{ top: -1, left: -1, borderRight: 'none', borderBottom: 'none' }} />
      <Corner style={{ top: -1, right: -1, borderLeft: 'none', borderBottom: 'none' }} />
      <Corner style={{ bottom: -1, left: -1, borderRight: 'none', borderTop: 'none' }} />
      <Corner style={{ bottom: -1, right: -1, borderLeft: 'none', borderTop: 'none' }} />
      {children}
    </div>
  );
}
const Corner = ({ style }) => (
  <span style={{
    position: 'absolute', width: 14, height: 14,
    border: `1px solid ${tokens.accent.base}`, pointerEvents: 'none', ...style,
  }} />
);

// Readout — telemetry label + value pair.
function Readout({ label, value, valueKind, sub, subKind }) {
  const valColor = ({ accent: tokens.accent.base, ok: tokens.ok.base, danger: tokens.danger.base, warn: tokens.warn.base }[valueKind]) || tokens.fg[1];
  const subColor = ({ ok: tokens.ok.base, danger: tokens.danger.base, warn: tokens.warn.base, accent: tokens.accent.base }[subKind]) || tokens.fg[3];
  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', gap: 4 }}>
      <Overline>— {label}</Overline>
      <div style={{
        fontFamily: tokens.font.mono, fontSize: 18, fontWeight: 600,
        color: valColor, letterSpacing: tokens.ls.data,
        fontVariantNumeric: 'tabular-nums',
        textShadow: valueKind === 'accent' ? tokens.accent.glowSm : 'none',
      }}>{value}</div>
      {sub && (
        <div style={{
          fontFamily: tokens.font.mono, fontSize: 10, color: subColor,
          letterSpacing: tokens.ls.overline,
        }}>{sub}</div>
      )}
    </div>
  );
}

// Bracket-wrapped label — "[ LIVE ]" "[ 404 ]"
function Bracket({ children, color }) {
  return (
    <span style={{
      fontFamily: tokens.font.mono, fontSize: 11,
      letterSpacing: tokens.ls.overline, color: color || tokens.accent.base,
    }}>
      <span style={{ opacity: 0.7 }}>[ </span>{children}<span style={{ opacity: 0.7 }}> ]</span>
    </span>
  );
}

function Card({ title, children, style }) {
  return (
    <div style={{
      background: tokens.bg.surface1,
      border: `1px solid ${tokens.border.base}`,
      borderRadius:6, padding: '16px 18px',
      ...style,
    }}>
      {title ? <Overline style={{ marginBottom: 10 }}>{title}</Overline> : null}
      {children}
    </div>
  );
}

function Badge({ kind = 'info', children, style }) {
  const map = {
    ok:     { bg: tokens.ok.soft,     fg: tokens.ok.base,     bd: tokens.ok.ring },
    danger: { bg: tokens.danger.soft, fg: tokens.danger.base, bd: tokens.danger.ring },
    warn:   { bg: tokens.warn.soft,   fg: tokens.warn.base,   bd: tokens.warn.ring },
    info:   { bg: tokens.info.soft,   fg: tokens.brand.text,  bd: tokens.info.ring },
  };
  const c = map[kind] || map.info;
  return (
    <span style={{
      display: 'inline-block', padding: '3px 10px', borderRadius:999,
      fontSize: 11, fontWeight: 600,
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`,
      ...style,
    }}>{children}</span>
  );
}

function Tag({ mode = 'inc', children }) {
  const c = mode === 'inc'
    ? { bg: tokens.ok.soft, fg: tokens.ok.base, bd: tokens.ok.ring }
    : { bg: tokens.danger.soft, fg: tokens.danger.base, bd: tokens.danger.ring };
  return (
    <span style={{
      display: 'inline-block', padding: '3px 10px', borderRadius:999,
      fontSize: 11, marginRight: 4, marginBottom: 3,
      fontFamily: tokens.font.mono,
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`,
    }}>{children}</span>
  );
}

function CheckRow({ kind = 'ok', label, value }) {
  const c = {
    ok:   { bg: tokens.ok.soft2,     bd: tokens.ok.soft,     icon: '✅' },
    fail: { bg: tokens.danger.soft2, bd: tokens.danger.soft, icon: '❌' },
    warn: { bg: tokens.warn.soft2,   bd: tokens.warn.soft,   icon: '⚠️' },
  }[kind];
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 10,
      padding: '10px 14px', borderRadius:4, marginBottom: 8,
      fontSize: 13, background: c.bg, border: `1px solid ${c.bd}`,
    }}>
      <span style={{ fontSize: 15, marginTop: 1 }}>{c.icon}</span>
      <div>
        <div style={{ fontSize: 11, color: tokens.fg[3] }}>{label}</div>
        <div style={{ color: tokens.fg[1], marginTop: 2, wordBreak: 'break-all' }}>{value}</div>
      </div>
    </div>
  );
}

function Metric({ label, value, kind }) {
  const valColor = ({ ok: tokens.ok.base, danger: tokens.danger.base, warn: tokens.warn.base }[kind]) || tokens.fg[1];
  return (
    <div style={{
      background: tokens.bg.surface1, border: `1px solid ${tokens.border.base}`,
      borderRadius:6, padding: '16px 18px',
    }}>
      <div style={{
        fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.08em',
        color: tokens.fg[3], marginBottom: 6,
      }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: valColor }}>{value}</div>
    </div>
  );
}

function Button({ variant = 'primary', onClick, children, style, disabled }) {
  const styles = {
    primary: { background: tokens.brand.base, color: '#fff', border: 'none' },
    hoverBg: tokens.brand.hover,
    ghost:   { background: 'transparent', color: tokens.fg[3], border: `1px solid ${tokens.border.input}` },
    danger:  { background: 'transparent', color: tokens.danger.base, border: `1px solid ${tokens.danger.ring}` },
    toggle:  { background: 'transparent', color: tokens.fg[3], border: `1px solid ${tokens.border.input}`, borderRadius:4, padding: '5px 12px', fontSize: 12 },
  };
  const [hover, setHover] = useState(false);
  const base = styles[variant] || styles.primary;
  const hoverStyle = !hover ? {} :
    variant === 'primary' ? { background: tokens.brand.hover } :
    { borderColor: tokens.brand.base, color: tokens.brand.text };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        fontFamily: tokens.font.sans, fontWeight: 500, fontSize: 13,
        borderRadius:4, padding: '9px 16px', cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'all .18s', opacity: disabled ? 0.5 : 1,
        ...base, ...hoverStyle, ...style,
      }}
    >{children}</button>
  );
}

function Input({ value, onChange, placeholder, style, type = 'text' }) {
  const [focus, setFocus] = useState(false);
  return (
    <input
      type={type}
      value={value || ''}
      onChange={e => onChange && onChange(e.target.value)}
      placeholder={placeholder}
      onFocus={() => setFocus(true)}
      onBlur={() => setFocus(false)}
      style={{
        background: tokens.bg.surface2,
        border: `1px solid ${focus ? tokens.brand.base : tokens.border.input}`,
        color: tokens.fg[1],
        borderRadius:4, padding: '9px 12px',
        fontFamily: tokens.font.sans, fontSize: 13, outline: 'none',
        boxShadow: focus ? `0 0 0 3px ${tokens.brand.ring}` : 'none',
        width: '100%', boxSizing: 'border-box', ...style,
      }}
    />
  );
}

function Select({ value, onChange, options = [], style }) {
  return (
    <select
      value={value}
      onChange={e => onChange && onChange(e.target.value)}
      style={{
        background: tokens.bg.surface2,
        border: `1px solid ${tokens.border.input}`,
        color: tokens.fg[1],
        borderRadius:4, padding: '9px 12px',
        fontFamily: tokens.font.sans, fontSize: 13, outline: 'none',
        width: '100%', appearance: 'none',
        backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M3 5l3 3 3-3' stroke='%238890b5' fill='none' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E")`,
        backgroundRepeat: 'no-repeat',
        backgroundPosition: 'right 10px center',
        paddingRight: 30,
        ...style,
      }}
    >
      {options.map(o => <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>)}
    </select>
  );
}

Object.assign(window, {
  Overline, SectionHeader, Card, Badge, Tag, CheckRow, Metric, Button, Input, Select,
  Led, HudPanel, Readout, Bracket,
});
