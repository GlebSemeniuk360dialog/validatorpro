// src/mobile-primitives.jsx — building blocks for Validator Pro Mobile.
// Mirrors the desktop kit's atoms but tuned for tap targets + mobile density.

const { useState: useStateMP } = React;

const T = window.tokens;

// ── Overline — caps tracked mono label, the system's hierarchy motif
function MOverline({ children, style }) {
  return (
    <div style={{
      fontFamily: T.font.mono, fontSize: 10, fontWeight: 500,
      textTransform: 'uppercase', letterSpacing: '0.14em',
      color: T.fg[3], ...style,
    }}>{children}</div>
  );
}

// ── SectionHeader — — accent + caps + hairline
function MSectionHeader({ children, style }) {
  return (
    <div style={{
      fontFamily: T.font.mono, fontSize: 10, fontWeight: 500,
      textTransform: 'uppercase', letterSpacing: '0.16em',
      color: T.fg[3], paddingBottom: 8, marginTop: 18, marginBottom: 10,
      borderBottom: `1px solid ${T.border.base}`,
      display: 'flex', alignItems: 'center', gap: 8, ...style,
    }}>
      <span style={{ color: T.accent.base, letterSpacing: 0 }}>—</span>
      <span>{children}</span>
    </div>
  );
}

// ── LED — 7px glowing dot
function MLed({ kind = 'accent', pulse, size = 7, style }) {
  const map = {
    accent: { c: T.accent.base, g: T.accent.glow },
    ok:     { c: T.ok.base, g: T.ok.glow },
    danger: { c: T.danger.base, g: T.danger.glow },
    warn:   { c: T.warn.base, g: T.warn.glow },
    brand:  { c: T.brand.base, g: T.brand.glow },
    dim:    { c: T.fg[4], g: 'none' },
  };
  const { c, g } = map[kind] || map.accent;
  return (
    <span style={{
      display: 'inline-block', width: size, height: size, borderRadius: '50%',
      background: c, boxShadow: g, flexShrink: 0,
      animation: pulse ? 'vp-led-pulse 1.6s ease-in-out infinite' : 'none',
      ...style,
    }} />
  );
}

// ── Corner brackets — HUD chrome for active record
function MCorners({ color, inset = 0 }) {
  const c = color || T.accent.base;
  const s = (extra) => ({
    position: 'absolute', width: 10, height: 10,
    border: `1px solid ${c}`, pointerEvents: 'none', ...extra,
  });
  return (
    <>
      <span style={s({ top: inset, left: inset, borderRight: 'none', borderBottom: 'none' })} />
      <span style={s({ top: inset, right: inset, borderLeft: 'none', borderBottom: 'none' })} />
      <span style={s({ bottom: inset, left: inset, borderRight: 'none', borderTop: 'none' })} />
      <span style={s({ bottom: inset, right: inset, borderLeft: 'none', borderTop: 'none' })} />
    </>
  );
}

// ── Card — white surface, 1px hairline, 6px radius
function MCard({ title, children, style, padding }) {
  const p = padding ?? '14px 14px';
  return (
    <div style={{
      background: T.bg.surface1, border: `1px solid ${T.border.base}`,
      borderRadius: 6, padding: p, ...style,
    }}>
      {title ? <MOverline style={{ marginBottom: 8 }}>{title}</MOverline> : null}
      {children}
    </div>
  );
}

// ── Badge / pill
function MBadge({ kind = 'info', children, style }) {
  const map = {
    ok:     { bg: T.ok.soft,     fg: T.ok.base,     bd: T.ok.ring },
    danger: { bg: T.danger.soft, fg: T.danger.base, bd: T.danger.ring },
    warn:   { bg: T.warn.soft,   fg: T.warn.base,   bd: T.warn.ring },
    info:   { bg: T.info.soft,   fg: T.brand.text,  bd: T.info.ring },
    neutral:{ bg: T.bg.surface3, fg: T.fg[2],       bd: T.border.base },
  };
  const c = map[kind] || map.info;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 9px', borderRadius: 999,
      fontSize: 10, fontWeight: 600, lineHeight: '16px',
      fontFamily: T.font.sans, letterSpacing: '0.02em',
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`,
      whiteSpace: 'nowrap', ...style,
    }}>{children}</span>
  );
}

// ── Tag (mono pill, used for filter/include tokens)
function MTag({ kind = 'neutral', children, style }) {
  const map = {
    ok:     { bg: T.ok.soft,     fg: T.ok.base,     bd: T.ok.ring },
    danger: { bg: T.danger.soft, fg: T.danger.base, bd: T.danger.ring },
    accent: { bg: T.accent.soft, fg: T.accent.base, bd: T.accent.ring },
    neutral:{ bg: T.bg.surface3, fg: T.fg[2],       bd: T.border.base },
  };
  const c = map[kind] || map.neutral;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 8px', borderRadius: 3,
      fontFamily: T.font.mono, fontSize: 10, letterSpacing: '0.04em',
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`,
      ...style,
    }}>{children}</span>
  );
}

// ── CheckRow — pass/fail/warn row with icon + label + value
function MCheckRow({ kind = 'ok', label, value }) {
  const map = {
    ok:   { bg: T.ok.soft2,     bd: T.ok.soft,     icon: '✓', col: T.ok.base },
    fail: { bg: T.danger.soft2, bd: T.danger.soft, icon: '✕', col: T.danger.base },
    warn: { bg: T.warn.soft2,   bd: T.warn.soft,   icon: '!', col: T.warn.base },
  };
  const c = map[kind] || map.ok;
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 10,
      padding: '10px 12px', borderRadius: 4, marginBottom: 6,
      fontSize: 12, background: c.bg, border: `1px solid ${c.bd}`,
    }}>
      <span style={{
        flexShrink: 0, width: 18, height: 18, borderRadius: '50%',
        background: c.col, color: '#fff', fontSize: 11, fontWeight: 700,
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        marginTop: 1,
      }}>{c.icon}</span>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 10, color: T.fg[3], letterSpacing: '0.04em' }}>{label}</div>
        <div style={{ color: T.fg[1], marginTop: 2, wordBreak: 'break-word', fontSize: 12 }}>{value}</div>
      </div>
    </div>
  );
}

// ── Buttons
function MButton({ variant = 'primary', onClick, children, style, disabled, fullWidth, size = 'md' }) {
  const sizes = {
    sm: { padding: '6px 12px', fontSize: 12, minHeight: 32 },
    md: { padding: '10px 16px', fontSize: 13, minHeight: 40 },
    lg: { padding: '12px 18px', fontSize: 14, minHeight: 48 },
  };
  const variants = {
    primary: { background: T.brand.base, color: '#fff', border: '1px solid transparent' },
    ghost:   { background: T.bg.surface1, color: T.fg[2], border: `1px solid ${T.border.input}` },
    soft:    { background: T.brand.soft, color: T.brand.text, border: `1px solid ${T.brand.ring}` },
    danger:  { background: T.bg.surface1, color: T.danger.base, border: `1px solid ${T.danger.ring}` },
    dark:    { background: T.brand.dark, color: '#fff', border: '1px solid transparent' },
  };
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        ...sizes[size], ...variants[variant],
        fontFamily: T.font.sans, fontWeight: 600, letterSpacing: '0.01em',
        borderRadius: 4, cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'all .18s', opacity: disabled ? 0.5 : 1,
        width: fullWidth ? '100%' : 'auto', whiteSpace: 'nowrap',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6,
        ...style,
      }}
    >{children}</button>
  );
}

// ── Input
function MInput({ value, onChange, placeholder, style, type = 'text', icon }) {
  const [focus, setFocus] = useStateMP(false);
  return (
    <div style={{ position: 'relative', width: '100%' }}>
      {icon && (
        <span style={{
          position: 'absolute', left: 11, top: '50%', transform: 'translateY(-50%)',
          color: T.fg[3], fontSize: 13, pointerEvents: 'none',
        }}>{icon}</span>
      )}
      <input
        type={type}
        value={value || ''}
        onChange={e => onChange && onChange(e.target.value)}
        placeholder={placeholder}
        onFocus={() => setFocus(true)}
        onBlur={() => setFocus(false)}
        style={{
          background: T.bg.surface1,
          border: `1px solid ${focus ? T.brand.base : T.border.input}`,
          color: T.fg[1],
          borderRadius: 4, padding: icon ? '11px 12px 11px 32px' : '11px 12px',
          fontFamily: T.font.sans, fontSize: 13, outline: 'none',
          boxShadow: focus ? `0 0 0 3px ${T.brand.ring}` : 'none',
          width: '100%', boxSizing: 'border-box',
          ...style,
        }}
      />
    </div>
  );
}

// ── Bracket text — [ LIVE ]
function MBracket({ children, color }) {
  return (
    <span style={{
      fontFamily: T.font.mono, fontSize: 10, fontWeight: 500,
      letterSpacing: '0.14em', color: color || T.accent.base, whiteSpace: 'nowrap',
    }}>
      <span style={{ opacity: 0.6 }}>[ </span>{children}<span style={{ opacity: 0.6 }}> ]</span>
    </span>
  );
}

// ── Readout — telemetry label + value
function MReadout({ label, value, valueKind, sub, subKind, size = 18 }) {
  const valColor = ({ accent: T.accent.base, ok: T.ok.base, danger: T.danger.base, warn: T.warn.base, brand: T.brand.text }[valueKind]) || T.fg[1];
  const subColor = ({ ok: T.ok.base, danger: T.danger.base, warn: T.warn.base, accent: T.accent.base }[subKind]) || T.fg[3];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, minWidth: 0 }}>
      <MOverline>— {label}</MOverline>
      <div style={{
        fontFamily: T.font.mono, fontSize: size, fontWeight: 600,
        color: valColor, letterSpacing: '0.04em',
        fontVariantNumeric: 'tabular-nums', lineHeight: 1.1,
      }}>{value}</div>
      {sub && (
        <div style={{
          fontFamily: T.font.mono, fontSize: 9, color: subColor,
          letterSpacing: '0.12em', textTransform: 'uppercase', marginTop: 2,
        }}>{sub}</div>
      )}
    </div>
  );
}

// ── URL Row
function MUrlRow({ icon = '🔗', url, kind = 'ok' }) {
  const col = ({ ok: T.ok.base, danger: T.danger.base, neutral: T.fg[2] }[kind]) || T.fg[2];
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '7px 10px', borderRadius: 4, marginBottom: 5,
      background: T.bg.surface2, border: `1px solid ${T.border.base}`,
      fontFamily: T.font.mono, fontSize: 10, wordBreak: 'break-all',
    }}>
      <span style={{ fontSize: 11 }}>{icon}</span>
      <span style={{ color: col, lineHeight: 1.4 }}>{url}</span>
    </div>
  );
}

Object.assign(window, {
  MOverline, MSectionHeader, MLed, MCorners, MCard, MBadge, MTag,
  MCheckRow, MButton, MInput, MBracket, MReadout, MUrlRow,
});
