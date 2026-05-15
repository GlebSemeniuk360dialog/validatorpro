// Tag Registry — redesigned to match the Sendout Validator design system
// Light scheme · teal #0fb5b5 brand · Space Grotesk + DM Sans + JetBrains Mono
const { useState, useEffect, useRef, useMemo } = React;

// ====================== tokens ======================
const T = {
  // surfaces
  bgApp: '#f6f8fb',
  bgCard: '#ffffff',
  bgHover: '#eef2f7',
  brandDark: '#0e2a2a',
  // text
  fg1: '#0f1828',
  fg2: '#475068',
  fg3: '#8893a3',
  fg4: '#aab3c1',
  // borders
  border1: '#e6eaef',
  border2: '#d6dce5',
  // brand
  brand: '#0fb5b5',
  brandHover: '#0ca0a0',
  brandText: '#0a8080',
  brandSoftBg: '#0fb5b515',
  brandSoftBorder: '#0fb5b540',
  // semantic
  ok: '#0c8f4a',
  okSoft: '#0c8f4a15',
  okRing: '#0c8f4a40',
  danger: '#dc2626',
  dangerSoft: '#dc262615',
  dangerRing: '#dc262640',
  warn: '#c47d0a',
  warnSoft: '#c47d0a15',
  warnRing: '#c47d0a40',
  accent: '#00a8c8',
  accentSoft: '#00a8c815',
  accentRing: '#00a8c840',
};

const fontDisplay = `'Space Grotesk', system-ui, sans-serif`;
const fontSans = `'DM Sans', system-ui, sans-serif`;
const fontMono = `'JetBrains Mono', ui-monospace, Menlo, monospace`;

// ====================== primitives ======================

const Overline = ({ children, accent, style }) => (
  <div style={{
    fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
    letterSpacing: '.08em',
    color: accent ? T.accent : T.fg3,
    fontFamily: fontSans,
    ...style,
  }}>{accent ? '— ' : ''}{children}</div>
);

const DashedRule = ({ color, style }) => (
  <hr style={{
    border: 'none',
    borderTop: `1px dashed ${color || T.border2}`,
    margin: 0,
    ...style,
  }}/>
);

// HUD corner brackets — reserved for active/focused panel
const HudFrame = ({ children, accent, style }) => (
  <div style={{
    position: 'relative',
    background: T.bgCard,
    border: `1px solid ${T.border1}`,
    borderRadius: 6,
    padding: '18px 22px',
    ...style,
  }}>
    <Bracket pos="tl" color={accent || T.accent}/>
    <Bracket pos="br" color={accent || T.accent}/>
    {children}
  </div>
);
const Bracket = ({ pos, color }) => {
  const styles = { position: 'absolute', width: 10, height: 10, borderStyle: 'solid', borderColor: color };
  const p = {
    tl: { top: -1, left: -1, borderWidth: '1.5px 0 0 1.5px' },
    tr: { top: -1, right: -1, borderWidth: '1.5px 1.5px 0 0' },
    bl: { bottom: -1, left: -1, borderWidth: '0 0 1.5px 1.5px' },
    br: { bottom: -1, right: -1, borderWidth: '0 1.5px 1.5px 0' },
  }[pos];
  return <span style={{ ...styles, ...p }}/>;
};

const Led = ({ tone = 'ok', pulse, size = 8 }) => {
  const color = { ok: T.ok, warn: T.warn, danger: T.danger, accent: T.accent, dim: T.fg4 }[tone];
  return (
    <span style={{
      display: 'inline-block', width: size, height: size, borderRadius: '50%',
      background: color,
      boxShadow: tone !== 'dim' ? `0 0 6px ${color}55` : 'none',
      animation: pulse ? 'led-pulse 1.8s ease-in-out infinite' : undefined,
    }}/>
  );
};

const Label = ({ children, required, hint }) => (
  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
    <span style={{
      fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.08em',
      color: T.fg3, fontFamily: fontSans,
    }}>{children}{required && <span style={{ color: T.brand, marginLeft: 4 }}>*</span>}</span>
    {hint && <span style={{ fontSize: 11, color: T.fg4, fontFamily: fontMono }}>{hint}</span>}
  </div>
);

const Input = ({ value, onChange, placeholder, mono, style, ...rest }) => (
  <input
    value={value || ''}
    onChange={e => onChange?.(e.target.value)}
    placeholder={placeholder}
    style={{
      width: '100%', height: 36, padding: '0 12px',
      fontFamily: mono ? fontMono : fontSans, fontSize: 13,
      color: T.fg1, background: T.bgCard,
      border: `1px solid ${T.border2}`, borderRadius: 4,
      outline: 'none', boxSizing: 'border-box',
      transition: 'border-color 120ms, box-shadow 120ms',
      ...style,
    }}
    onFocus={e => { e.target.style.borderColor = T.brand; e.target.style.boxShadow = `0 0 0 3px ${T.brand}22`; }}
    onBlur={e => { e.target.style.borderColor = T.border2; e.target.style.boxShadow = 'none'; }}
    {...rest}
  />
);

const Select = ({ value, onChange, options, placeholder, disabled, mono, style }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const onDoc = e => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);
  const display = options?.find(o => o.value === value);
  return (
    <div ref={ref} style={{ position: 'relative', ...style }}>
      <button type="button" disabled={disabled} onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', height: 36, padding: '0 32px 0 12px',
          background: disabled ? T.bgApp : T.bgCard,
          border: `1px solid ${open ? T.brand : T.border2}`,
          boxShadow: open ? `0 0 0 3px ${T.brand}22` : 'none',
          borderRadius: 4,
          fontFamily: mono ? fontMono : fontSans, fontSize: 13,
          color: display ? T.fg1 : T.fg4,
          textAlign: 'left', cursor: disabled ? 'not-allowed' : 'pointer',
        }}>
        {display?.label || placeholder}
        <svg width="10" height="10" viewBox="0 0 12 12" style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)' }}>
          <path d="M2 4l4 4 4-4" stroke={T.fg3} strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', left: 0, right: 0, zIndex: 30,
          background: T.bgCard, border: `1px solid ${T.border2}`, borderRadius: 4,
          boxShadow: '0 8px 24px rgba(15,23,42,0.08)', maxHeight: 240, overflow: 'auto',
        }}>
          {options?.map(o => (
            <div key={o.value} onClick={() => { onChange?.(o.value); setOpen(false); }}
              style={{
                padding: '8px 12px', fontSize: 13, cursor: 'pointer',
                color: T.fg1, fontFamily: mono ? fontMono : fontSans,
                background: o.value === value ? T.brandSoftBg : T.bgCard,
              }}
              onMouseEnter={e => { if (o.value !== value) e.currentTarget.style.background = T.bgHover; }}
              onMouseLeave={e => { if (o.value !== value) e.currentTarget.style.background = T.bgCard; }}>
              {o.label}
              {o.sub && <div style={{ fontSize: 11, color: T.fg3, marginTop: 2, fontFamily: fontMono }}>{o.sub}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const Btn = ({ children, primary, ghost, small, onClick, glyph, disabled, style }) => {
  const base = {
    height: small ? 28 : 36,
    padding: small ? '0 10px' : '0 16px',
    fontFamily: fontSans, fontSize: small ? 12 : 13, fontWeight: 500,
    borderRadius: 4, border: '1px solid transparent', cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1,
    display: 'inline-flex', alignItems: 'center', gap: 6,
    transition: 'background 140ms, border-color 140ms, color 140ms',
  };
  if (primary) Object.assign(base, { background: T.brand, color: '#fff' });
  else if (ghost) Object.assign(base, { background: 'transparent', color: T.fg3, border: `1px solid ${T.border2}` });
  else Object.assign(base, { background: T.bgCard, color: T.fg2, border: `1px solid ${T.border2}` });
  return (
    <button type="button" onClick={onClick} disabled={disabled} style={{ ...base, ...style }}
      onMouseEnter={e => {
        if (disabled) return;
        if (primary) e.currentTarget.style.background = T.brandHover;
        else { e.currentTarget.style.borderColor = T.brand; e.currentTarget.style.color = T.brandText; }
      }}
      onMouseLeave={e => {
        if (primary) e.currentTarget.style.background = T.brand;
        else { e.currentTarget.style.borderColor = T.border2; e.currentTarget.style.color = ghost ? T.fg3 : T.fg2; }
      }}>
      {glyph && <span style={{ fontFamily: fontMono, fontSize: small ? 11 : 12 }}>{glyph}</span>}
      {children}
    </button>
  );
};

const Tag = ({ children, tone = 'include', onRemove }) => {
  const palette = {
    include: { bg: '#00d4aa18', fg: '#0a8080', border: '#0fb5b540' },
    exclude: { bg: '#ff4d6d18', fg: '#9F1239', border: '#dc262640' },
    neutral: { bg: T.bgHover, fg: T.fg2, border: T.border2 },
  }[tone];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: onRemove ? '2px 4px 2px 10px' : '3px 10px',
      background: palette.bg, color: palette.fg,
      border: `1px solid ${palette.border}`, borderRadius: 999,
      fontFamily: fontMono, fontSize: 11, fontWeight: 500, lineHeight: 1.4,
    }}>
      {children}
      {onRemove && (
        <button onClick={onRemove} style={{
          width: 14, height: 14, border: 'none', background: 'transparent',
          color: palette.fg, opacity: 0.55, cursor: 'pointer', padding: 0,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center', borderRadius: '50%',
        }}>
          <svg width="8" height="8" viewBox="0 0 9 9"><path d="M1 1l7 7M8 1l-7 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
        </button>
      )}
    </span>
  );
};

const TagInput = ({ tags, setTags, placeholder, tone }) => {
  const [draft, setDraft] = useState('');
  const [focused, setFocused] = useState(false);
  const commit = () => {
    const v = draft.trim().replace(/,$/, '');
    if (v && !tags.includes(v)) setTags([...tags, v]);
    setDraft('');
  };
  return (
    <div style={{
      minHeight: 76, padding: 7,
      background: T.bgCard,
      border: `1px solid ${focused ? T.brand : T.border2}`,
      boxShadow: focused ? `0 0 0 3px ${T.brand}22` : 'none',
      borderRadius: 4,
      display: 'flex', flexWrap: 'wrap', gap: 5, alignContent: 'flex-start',
      transition: 'border-color 120ms, box-shadow 120ms',
    }}>
      {tags.map(t => (
        <Tag key={t} tone={tone} onRemove={() => setTags(tags.filter(x => x !== t))}>{t}</Tag>
      ))}
      <input
        value={draft}
        onChange={e => {
          const v = e.target.value;
          if (v.endsWith(',') || v.endsWith('\n')) {
            const x = v.replace(/[,\n]$/, '').trim();
            if (x && !tags.includes(x)) setTags([...tags, x]);
            setDraft('');
          } else setDraft(v);
        }}
        onKeyDown={e => {
          if (e.key === 'Enter') { e.preventDefault(); commit(); }
          if (e.key === 'Backspace' && !draft && tags.length) setTags(tags.slice(0, -1));
        }}
        onFocus={() => setFocused(true)}
        onBlur={() => { setFocused(false); commit(); }}
        placeholder={tags.length ? '' : placeholder}
        style={{
          flex: 1, minWidth: 120, border: 'none', outline: 'none',
          fontFamily: fontMono, fontSize: 11.5, color: T.fg1,
          background: 'transparent', padding: '3px 6px',
        }}
      />
    </div>
  );
};

const Hint = ({ children }) => (
  <div style={{ marginTop: 6, fontSize: 11, color: T.fg3, fontFamily: fontSans, lineHeight: 1.5 }}>{children}</div>
);

// shared data
const clients = [
  { value: 'aldi-sued', label: 'ALDI Sued', sub: 'account_id = 79' },
  { value: 'aldi-nord', label: 'ALDI Nord', sub: 'account_id = 88' },
  { value: 'lidl', label: 'Lidl', sub: 'account_id = 102' },
  { value: 'rewe', label: 'REWE', sub: 'account_id = 64' },
];
const tickets = [
  { value: 'MAS-4141', label: 'MAS-4141', sub: 'Week 21 leaflet · double opt-in' },
  { value: 'MAS-4112', label: 'MAS-4112', sub: 'Week 20 · declined-terms exclusion' },
  { value: 'MAS-4078', label: 'MAS-4078', sub: 'Week 19 · baseline sendout' },
];
const sendouts = [
  { value: '9b3f-8e8c-2c4f-aaaa', label: '9b3f-8e8c-2c4f-aaaa', sub: 'ALDI Sued Woche 21 · 142,310 rcpts' },
  { value: '8a2e-7d7b-1b3e-bbbb', label: '8a2e-7d7b-1b3e-bbbb', sub: 'ALDI Sued Woche 20 · 141,005 rcpts' },
];

// ====================== Direction A — Console (sectioned form, HUD active panel) ======================
function DirectionA() {
  const [form, setForm] = useState({
    client: 'aldi-sued', ticket: 'MAS-4141', sendout: '9b3f-8e8c-2c4f-aaaa',
    label: 'ALDI Sued Woche 21',
    date: '21.05.2026', time: '06:00', tz: 'Europe/Berlin',
  });
  const [include, setInclude] = useState(['leaflet_accepted=true', 'offset_days=1', 'shop_number=12345']);
  const [exclude, setExclude] = useState(['declined_new_terms=true']);
  const set = k => v => setForm(f => ({ ...f, [k]: v }));

  const sections = [
    { id: 'targeting', label: 'Targeting',  glyph: '01', count: '2/2' },
    { id: 'source',    label: 'Source',     glyph: '02', count: '1/1' },
    { id: 'schedule',  label: 'Schedule',   glyph: '03', count: '3/3' },
    { id: 'rules',     label: 'Tag rules',  glyph: '04', count: `${include.length}+${exclude.length}`, active: true },
  ];

  return (
    <div style={{ width: 1180, height: 820, background: T.bgApp, fontFamily: fontSans, color: T.fg1, display: 'flex', flexDirection: 'column' }}>
      {/* App bar */}
      <div style={{ height: 56, padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: T.bgCard, borderBottom: `1px solid ${T.border1}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ width: 26, height: 26, borderRadius: 4, background: T.brandDark, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#b3dfdf', fontFamily: fontMono, fontSize: 12, fontWeight: 600 }}>SV</div>
          <div style={{ fontFamily: fontMono, fontSize: 12, color: T.fg3, letterSpacing: '.04em' }}>
            <span style={{ color: T.fg2 }}>tag-registry</span>
            <span style={{ margin: '0 8px', color: T.fg4 }}>›</span>
            <span style={{ color: T.fg1 }}>new</span>
          </div>
          <Led tone="ok" pulse/>
          <span style={{ fontFamily: fontMono, fontSize: 11, color: T.fg3, letterSpacing: '.12em', textTransform: 'uppercase' }}>DMA · 200 OK</span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <Btn ghost>Cancel</Btn>
          <Btn primary glyph="▶">Create entry</Btn>
        </div>
      </div>

      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '240px 1fr', overflow: 'hidden' }}>
        {/* Sidebar */}
        <div style={{ padding: 20, background: T.bgCard, borderRight: `1px solid ${T.border1}`, display: 'flex', flexDirection: 'column', gap: 4 }}>
          <Overline style={{ marginBottom: 10 }}>— Sections</Overline>
          {sections.map(s => (
            <div key={s.id} style={{
              padding: '8px 10px', borderRadius: 4, display: 'flex', alignItems: 'center', gap: 10,
              background: s.active ? T.brandSoftBg : 'transparent',
              border: s.active ? `1px solid ${T.brandSoftBorder}` : '1px solid transparent',
              cursor: 'pointer',
            }}>
              <span style={{ fontFamily: fontMono, fontSize: 10, color: s.active ? T.brandText : T.fg4, letterSpacing: '.04em' }}>{s.glyph}</span>
              <span style={{ fontSize: 13, fontWeight: s.active ? 500 : 400, color: s.active ? T.fg1 : T.fg2, flex: 1 }}>{s.label}</span>
              <span style={{ fontFamily: fontMono, fontSize: 10, color: s.active ? T.brandText : T.fg4 }}>{s.count}</span>
            </div>
          ))}
          <DashedRule style={{ margin: '16px 0' }}/>
          <Overline style={{ marginBottom: 10 }}>— Validation</Overline>
          <div style={{ fontFamily: fontMono, fontSize: 11, color: T.fg2, lineHeight: 1.7 }}>
            <div>match_key  = <span style={{ color: T.brandText }}>{form.ticket}</span></div>
            <div>overrides  = <span style={{ color: T.brandText }}>g-sheet</span></div>
            <div>scope      = <span style={{ color: T.brandText }}>sendout</span></div>
          </div>
          <div style={{ marginTop: 14, padding: '10px 12px', background: T.brandSoftBg, border: `1px solid ${T.brandSoftBorder}`, borderRadius: 4, fontSize: 11, color: T.brandText, lineHeight: 1.55 }}>
            Entry overrides Google Sheets when the Jira key matches at sendout time.
          </div>
        </div>

        {/* Form */}
        <div style={{ overflowY: 'auto', padding: '24px 28px 80px' }}>
          {/* breadcrumb-style title */}
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 6 }}>
            <div style={{ fontFamily: fontDisplay, fontSize: 22, fontWeight: 600, letterSpacing: '-0.02em' }}>New registry entry</div>
            <div style={{ fontFamily: fontMono, fontSize: 11, color: T.fg3 }}>draft · auto-saved <span style={{ color: T.ok }}>14:02:11</span></div>
          </div>
          <div style={{ fontSize: 13, color: T.fg2, marginBottom: 22 }}>Per-sendout include / exclude tags — used instead of Google Sheets when matched.</div>

          {/* Targeting */}
          <SectionA glyph="01" title="Targeting" subtitle="Who this entry applies to.">
            <Row cols="1fr 1.3fr">
              <Field><Label required>Client</Label><Select value={form.client} onChange={set('client')} options={clients} placeholder="— select client —"/></Field>
              <Field><Label hint="auto-fills sendout + date">Jira ticket</Label><Select value={form.ticket} onChange={set('ticket')} options={tickets} placeholder="— pick a ticket —" mono/></Field>
            </Row>
          </SectionA>

          {/* Source */}
          <SectionA glyph="02" title="Source" subtitle="The DMA sendout this entry attaches to.">
            <Field><Label>Sendout (from DMA)</Label><Select value={form.sendout} onChange={set('sendout')} options={sendouts} placeholder="— select —" mono/></Field>
            <div style={{ height: 14 }}/>
            <Field><Label>Sendout name (label)</Label><Input value={form.label} onChange={set('label')}/></Field>
          </SectionA>

          {/* Schedule */}
          <SectionA glyph="03" title="Schedule">
            <Row cols="1fr 1fr 1.3fr">
              <Field><Label>Date</Label><Input value={form.date} onChange={set('date')} placeholder="DD.MM.YYYY" mono/></Field>
              <Field><Label>Time · 24h</Label><Input value={form.time} onChange={set('time')} placeholder="--:--" mono/></Field>
              <Field><Label>Timezone</Label><Select value={form.tz} onChange={set('tz')} options={[
                { value: 'Europe/Berlin', label: 'Europe/Berlin' },
                { value: 'Europe/London', label: 'Europe/London' },
                { value: 'UTC', label: 'UTC' },
              ]}/></Field>
            </Row>
          </SectionA>

          {/* Rules — active HUD section */}
          <div style={{ marginBottom: 24 }}>
            <SectionHeader glyph="04" title="Tag rules" subtitle="Comma, Enter or newline to add a tag." accent/>
            <HudFrame accent={T.brand} style={{ padding: '18px 20px' }}>
              <Row cols="1fr 1fr">
                <Field>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <Led tone="ok" size={6}/>
                    <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.08em', color: T.fg3 }}>Include · {include.length}</span>
                  </div>
                  <TagInput tags={include} setTags={setInclude} tone="include" placeholder="leaflet_accepted=true"/>
                  <Hint>All include rules must match the recipient.</Hint>
                </Field>
                <Field>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <Led tone="danger" size={6}/>
                    <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.08em', color: T.fg3 }}>Exclude · {exclude.length}</span>
                  </div>
                  <TagInput tags={exclude} setTags={setExclude} tone="exclude" placeholder="declined_new_terms=true"/>
                  <Hint>Any match drops the recipient from the sendout.</Hint>
                </Field>
              </Row>
            </HudFrame>
          </div>

        </div>
      </div>
    </div>
  );
}

const SectionHeader = ({ glyph, title, subtitle, accent }) => (
  <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, padding: '0 0 10px', borderBottom: `1px solid ${T.border1}`, marginBottom: 14 }}>
    <span style={{ fontFamily: fontMono, fontSize: 11, fontWeight: 600, color: accent ? T.brandText : T.fg3, letterSpacing: '.08em' }}>{glyph}</span>
    <span style={{ fontFamily: fontDisplay, fontSize: 14, fontWeight: 600, color: T.fg1 }}>{title}</span>
    {subtitle && <span style={{ fontSize: 12, color: T.fg3 }}>{subtitle}</span>}
  </div>
);
const SectionA = ({ glyph, title, subtitle, children }) => (
  <div style={{ marginBottom: 24 }}>
    <SectionHeader glyph={glyph} title={title} subtitle={subtitle}/>
    {children}
  </div>
);
const Row = ({ cols, children }) => <div style={{ display: 'grid', gridTemplateColumns: cols, gap: 14 }}>{children}</div>;
const Field = ({ children, style }) => <div style={style}>{children}</div>;

// ====================== Direction B — Live readout (form + resolved-rule HUD) ======================
function DirectionB() {
  const [form, setForm] = useState({
    client: 'aldi-sued', ticket: 'MAS-4141', sendout: '9b3f-8e8c-2c4f-aaaa',
    label: 'ALDI Sued Woche 21',
    date: '21.05.2026', time: '06:00', tz: 'Europe/Berlin',
    notes: '',
  });
  const [include, setInclude] = useState(['leaflet_accepted=true', 'offset_days=1']);
  const [exclude, setExclude] = useState(['declined_new_terms=true']);
  const set = k => v => setForm(f => ({ ...f, [k]: v }));

  const client = clients.find(c => c.value === form.client);
  const sendout = sendouts.find(s => s.value === form.sendout);
  const matchedCount = 142310;
  const dropped = Math.floor(matchedCount * 0.022);

  return (
    <div style={{ width: 1180, height: 820, background: T.bgApp, fontFamily: fontSans, color: T.fg1, display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div style={{ padding: '22px 28px 18px', background: T.bgCard, borderBottom: `1px solid ${T.border1}`, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontFamily: fontDisplay, fontSize: 22, fontWeight: 600, letterSpacing: '-0.02em' }}>Tag Registry</div>
          <div style={{ fontSize: 13, color: T.fg2, marginTop: 4 }}>Per-sendout include / exclude tags — used instead of Google Sheets when matched.</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Led tone="ok" pulse size={7}/>
            <span style={{ fontFamily: fontMono, fontSize: 11, color: T.fg3, letterSpacing: '.12em', textTransform: 'uppercase' }}>DMA · live</span>
          </div>
          <Btn primary glyph="＋">New entry</Btn>
        </div>
      </div>

      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 410px', overflow: 'hidden' }}>
        {/* Form */}
        <div style={{ padding: 26, overflowY: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18 }}>
            <span style={{ fontFamily: fontMono, fontSize: 11, color: T.brandText, letterSpacing: '.12em', textTransform: 'uppercase' }}>— New registry entry</span>
            <DashedRule style={{ flex: 1 }}/>
          </div>

          <Row cols="1fr 1.3fr">
            <Field><Label required>Client</Label><Select value={form.client} onChange={set('client')} options={clients} placeholder="— select client —"/></Field>
            <Field><Label>Jira ticket</Label><Select value={form.ticket} onChange={set('ticket')} options={tickets} mono/>
              <Hint>Auto-fills the sendout & date. Enables exact ticket-key matching at validation.</Hint>
            </Field>
          </Row>

          <div style={{ height: 16 }}/>
          <Field><Label>Sendout · from DMA</Label><Select value={form.sendout} onChange={set('sendout')} options={sendouts} mono/></Field>

          <div style={{ height: 16 }}/>
          <Row cols="1.6fr 1fr 1fr 1.2fr">
            <Field><Label>Sendout name</Label><Input value={form.label} onChange={set('label')}/></Field>
            <Field><Label>Date</Label><Input value={form.date} onChange={set('date')} mono/></Field>
            <Field><Label>Time</Label><Input value={form.time} onChange={set('time')} mono/></Field>
            <Field><Label>Timezone</Label><Select value={form.tz} onChange={set('tz')} options={[
              { value: 'Europe/Berlin', label: 'Europe/Berlin' },
              { value: 'UTC', label: 'UTC' },
            ]}/></Field>
          </Row>

          <div style={{ height: 22 }}/>
          <Row cols="1fr 1fr">
            <Field>
              <Label>Include tags</Label>
              <TagInput tags={include} setTags={setInclude} tone="include" placeholder="key=value"/>
              <Hint>All must match the recipient.</Hint>
            </Field>
            <Field>
              <Label>Exclude tags</Label>
              <TagInput tags={exclude} setTags={setExclude} tone="exclude" placeholder="key=value"/>
              <Hint>Any match drops the recipient.</Hint>
            </Field>
          </Row>

          <div style={{ height: 16 }}/>
          <Field><Label hint="optional">Notes</Label><Input value={form.notes} onChange={set('notes')} placeholder="e.g. Week 21 — special promo, double opt-in required"/></Field>

          <div style={{ height: 26 }}/>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Btn primary glyph="▶">Create entry</Btn>
            <Btn ghost>Cancel</Btn>
            <div style={{ flex: 1 }}/>
            <div style={{ fontFamily: fontMono, fontSize: 11, color: T.fg4 }}>nothing is saved until create</div>
          </div>
        </div>

        {/* Live HUD preview */}
        <div style={{ background: T.bgApp, borderLeft: `1px solid ${T.border1}`, padding: 22, overflowY: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
            <Led tone="accent" pulse size={7}/>
            <span style={{ fontFamily: fontMono, fontSize: 11, color: T.accent, letterSpacing: '.12em', textTransform: 'uppercase' }}>— Resolved · live preview</span>
          </div>

          {/* HUD identity panel */}
          <HudFrame accent={T.accent} style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
              <span style={{ fontFamily: fontMono, fontSize: 11, color: T.brandText, padding: '2px 8px', background: T.brandSoftBg, border: `1px solid ${T.brandSoftBorder}`, borderRadius: 3 }}>{form.ticket}</span>
              <span style={{ fontFamily: fontMono, fontSize: 11, color: T.fg3 }}>LIVE</span>
            </div>
            <div style={{ fontFamily: fontMono, fontSize: 12, color: T.fg1, letterSpacing: '.02em', lineHeight: 1.8 }}>
              <div>sendout = <span style={{ color: T.brandText }}>{form.sendout}</span></div>
              <div>client  = <span style={{ color: T.brandText }}>{client?.label}</span> <span style={{ color: T.fg4 }}>· {client?.sub}</span></div>
              <div>fires   = <span style={{ color: T.brandText }}>{form.date} {form.time}</span> <span style={{ color: T.fg4 }}>· {form.tz}</span></div>
            </div>
          </HudFrame>

          {/* Readouts */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 12 }}>
            <Readout label="— Recipients" value={matchedCount.toLocaleString('de-DE')} sub="DMA snapshot"/>
            <Readout label="— Will drop"  value={dropped.toLocaleString('de-DE')} tone="danger" sub={`${(dropped/matchedCount*100).toFixed(1)}% match exclude`}/>
            <Readout label="— Net send"   value={(matchedCount-dropped).toLocaleString('de-DE')} tone="ok" sub="after rules"/>
          </div>

          {/* Resolved rule */}
          <div style={{ background: T.bgCard, border: `1px solid ${T.border1}`, borderRadius: 6, padding: 14, marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <Overline>— Resolved rule</Overline>
              <DashedRule style={{ flex: 1 }}/>
            </div>
            <div style={{ fontFamily: fontMono, fontSize: 11.5, color: T.fg1, lineHeight: 1.8, padding: 10, background: T.bgApp, borderRadius: 4, border: `1px solid ${T.border1}` }}>
              <div><span style={{ color: T.brandText }}>WHERE</span> {include.length ? include.join(' AND ') : '*'}</div>
              {exclude.length > 0 && (
                <div><span style={{ color: T.danger }}>AND NOT</span> ({exclude.join(' OR ')})</div>
              )}
            </div>
          </div>

          {/* Tag groups */}
          <PreviewBlock title={`Include · ${include.length}`} tone="ok" empty="No include rules — sendout matches all recipients.">
            {include.map(t => <Tag key={t} tone="include">{t}</Tag>)}
          </PreviewBlock>
          <PreviewBlock title={`Exclude · ${exclude.length}`} tone="danger" empty="No exclude rules.">
            {exclude.map(t => <Tag key={t} tone="exclude">{t}</Tag>)}
          </PreviewBlock>
        </div>
      </div>
    </div>
  );
}

const Readout = ({ label, value, sub, tone }) => {
  const color = { ok: T.ok, danger: T.danger, warn: T.warn, accent: T.accent }[tone] || T.fg1;
  return (
    <div style={{ background: T.bgCard, border: `1px solid ${T.border1}`, borderRadius: 6, padding: '12px 12px' }}>
      <div style={{ fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.08em', color: T.fg3, marginBottom: 6 }}>{label}</div>
      <div style={{ fontFamily: fontMono, fontSize: 18, fontWeight: 600, color, fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.01em' }}>{value}</div>
      {sub && <div style={{ fontFamily: fontMono, fontSize: 10, color: T.fg3, marginTop: 4 }}>{sub}</div>}
    </div>
  );
};
const PreviewBlock = ({ title, tone, children, empty }) => {
  const arr = React.Children.toArray(children);
  return (
    <div style={{ background: T.bgCard, border: `1px solid ${T.border1}`, borderRadius: 6, padding: 12, marginBottom: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <Led tone={tone} size={6}/>
        <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.08em', color: T.fg3 }}>{title}</span>
      </div>
      {arr.length ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>{children}</div>
      ) : (
        <div style={{ fontFamily: fontMono, fontSize: 11, color: T.fg4 }}>{empty}</div>
      )}
    </div>
  );
};

// ====================== Direction C — Wizard with mono breadcrumb ======================
function DirectionC() {
  const steps = [
    { id: 'client',  label: 'Client & ticket' },
    { id: 'sendout', label: 'Sendout' },
    { id: 'tags',    label: 'Tag rules' },
    { id: 'review',  label: 'Review' },
  ];
  const [active, setActive] = useState(2);
  const [form, setForm] = useState({
    client: 'aldi-sued', ticket: 'MAS-4141', sendout: '9b3f-8e8c-2c4f-aaaa',
    label: 'ALDI Sued Woche 21',
    date: '21.05.2026', time: '06:00', tz: 'Europe/Berlin',
    notes: '',
  });
  const [include, setInclude] = useState(['leaflet_accepted=true', 'offset_days=1']);
  const [exclude, setExclude] = useState(['declined_new_terms=true']);
  const set = k => v => setForm(f => ({ ...f, [k]: v }));
  const clientLbl = clients.find(c => c.value === form.client)?.label;

  return (
    <div style={{ width: 1180, height: 820, background: T.bgApp, fontFamily: fontSans, color: T.fg1, display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div style={{ padding: '20px 28px', background: T.bgCard, borderBottom: `1px solid ${T.border1}` }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontFamily: fontDisplay, fontSize: 22, fontWeight: 600, letterSpacing: '-0.02em' }}>Tag Registry — new entry</div>
            <div style={{ fontFamily: fontMono, fontSize: 12, color: T.fg3, marginTop: 4, letterSpacing: '.04em' }}>
              step <span style={{ color: T.brandText }}>{String(active+1).padStart(2,'0')}</span> / {String(steps.length).padStart(2,'0')} · {steps[active].label}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <Led tone="ok" pulse size={7}/>
            <span style={{ fontFamily: fontMono, fontSize: 11, color: T.fg3, letterSpacing: '.12em', textTransform: 'uppercase' }}>autosave on</span>
          </div>
        </div>

        {/* Mono stepper */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 18 }}>
          {steps.map((s, i) => (
            <React.Fragment key={s.id}>
              <div onClick={() => setActive(i)} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <div style={{
                  width: 22, height: 22, borderRadius: 3,
                  background: i < active ? T.brand : (i === active ? T.bgCard : T.bgApp),
                  border: `1px solid ${i <= active ? T.brand : T.border2}`,
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  fontFamily: fontMono, fontSize: 11, fontWeight: 600,
                  color: i < active ? '#fff' : (i === active ? T.brandText : T.fg4),
                }}>{i < active ? '✓' : String(i+1).padStart(2,'0')}</div>
                <span style={{ fontSize: 13, fontWeight: i === active ? 500 : 400, color: i === active ? T.fg1 : (i < active ? T.fg2 : T.fg4) }}>{s.label}</span>
              </div>
              {i < steps.length - 1 && (
                <div style={{ flex: 1, height: 0, borderTop: `1px dashed ${i < active ? T.brand : T.border2}` }}/>
              )}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* Body */}
      <div style={{ flex: 1, padding: '32px 28px', overflowY: 'auto', display: 'flex', justifyContent: 'center' }}>
        <div style={{ width: 680 }}>
          {/* Active record breadcrumb */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 16, fontFamily: fontMono, fontSize: 11, color: T.fg3, letterSpacing: '.02em' }}>
            <span style={{ color: T.brandText }}>{form.ticket}</span>
            <span style={{ color: T.fg4 }}>·</span>
            <span>{clientLbl}</span>
            <span style={{ color: T.fg4 }}>·</span>
            <span>{form.date} {form.time}</span>
            <span style={{ color: T.fg4 }}>·</span>
            <span>{form.tz}</span>
          </div>

          {active === 0 && (
            <CardC glyph="01" title="Client & ticket" subtitle="Select who this registry entry belongs to.">
              <Field><Label required>Client</Label><Select value={form.client} onChange={set('client')} options={clients} placeholder="— select client —"/></Field>
              <div style={{ height: 16 }}/>
              <Field><Label>Jira ticket</Label><Select value={form.ticket} onChange={set('ticket')} options={tickets} mono/>
                <Hint>Auto-fills the sendout below. Enables exact ticket-key matching at validation.</Hint>
              </Field>
            </CardC>
          )}
          {active === 1 && (
            <CardC glyph="02" title="Sendout" subtitle="Schedule, label, and DMA source.">
              <Field><Label>Sendout · from DMA</Label><Select value={form.sendout} onChange={set('sendout')} options={sendouts} mono/></Field>
              <div style={{ height: 16 }}/>
              <Field><Label>Sendout name (label)</Label><Input value={form.label} onChange={set('label')}/></Field>
              <div style={{ height: 16 }}/>
              <Row cols="1fr 1fr 1.2fr">
                <Field><Label>Date</Label><Input value={form.date} onChange={set('date')} mono/></Field>
                <Field><Label>Time</Label><Input value={form.time} onChange={set('time')} mono/></Field>
                <Field><Label>Timezone</Label><Select value={form.tz} onChange={set('tz')} options={[{ value: 'Europe/Berlin', label: 'Europe/Berlin' }, { value: 'UTC', label: 'UTC' }]}/></Field>
              </Row>
            </CardC>
          )}
          {active === 2 && (
            <CardC glyph="03" title="Tag rules" subtitle="Comma, Enter or newline to add a tag.">
              <Field>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <Led tone="ok" size={6}/>
                  <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.08em', color: T.fg3 }}>Include · {include.length}</span>
                </div>
                <TagInput tags={include} setTags={setInclude} tone="include" placeholder="leaflet_accepted=true"/>
                <Hint>All include rules must match the recipient.</Hint>
              </Field>
              <div style={{ height: 16 }}/>
              <Field>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <Led tone="danger" size={6}/>
                  <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.08em', color: T.fg3 }}>Exclude · {exclude.length}</span>
                </div>
                <TagInput tags={exclude} setTags={setExclude} tone="exclude" placeholder="declined_new_terms=true"/>
                <Hint>Any match drops the recipient from the sendout.</Hint>
              </Field>
              <div style={{ height: 16 }}/>
              <Field><Label hint="optional">Notes</Label><Input value={form.notes} onChange={set('notes')} placeholder="e.g. Week 21 — special promo"/></Field>
            </CardC>
          )}
          {active === 3 && (
            <CardC glyph="04" title="Review" subtitle="Confirm and create — nothing is saved until you press the button.">
              <ReviewRow label="Client" value={`${clientLbl} · ${clients.find(c=>c.value===form.client)?.sub}`}/>
              <ReviewRow label="Jira ticket" value={form.ticket} mono/>
              <ReviewRow label="Sendout" value={form.sendout} mono/>
              <ReviewRow label="When" value={`${form.date} ${form.time} · ${form.tz}`}/>
              <ReviewRow label="Include">
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>{include.map(t => <Tag key={t} tone="include">{t}</Tag>)}</div>
              </ReviewRow>
              <ReviewRow label="Exclude">
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>{exclude.map(t => <Tag key={t} tone="exclude">{t}</Tag>)}</div>
              </ReviewRow>
            </CardC>
          )}
        </div>
      </div>

      {/* Footer */}
      <div style={{ padding: '14px 28px', background: T.bgCard, borderTop: `1px solid ${T.border1}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Btn ghost onClick={() => setActive(a => Math.max(0, a-1))} disabled={active === 0} glyph="←">Back</Btn>
        <div style={{ fontFamily: fontMono, fontSize: 11, color: T.fg4 }}>esc to cancel — no changes saved</div>
        {active < steps.length - 1
          ? <Btn primary onClick={() => setActive(a => Math.min(steps.length - 1, a+1))} glyph="→">Continue</Btn>
          : <Btn primary glyph="▶">Create entry</Btn>}
      </div>
    </div>
  );
}

const CardC = ({ glyph, title, subtitle, children }) => (
  <div style={{ background: T.bgCard, border: `1px solid ${T.border1}`, borderRadius: 6, padding: '24px 28px' }}>
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, paddingBottom: 14, marginBottom: 18, borderBottom: `1px solid ${T.border1}` }}>
      <span style={{ fontFamily: fontMono, fontSize: 11, fontWeight: 600, color: T.brandText, letterSpacing: '.08em' }}>{glyph}</span>
      <span style={{ fontFamily: fontDisplay, fontSize: 16, fontWeight: 600 }}>{title}</span>
      {subtitle && <span style={{ fontSize: 12, color: T.fg3 }}>{subtitle}</span>}
    </div>
    {children}
  </div>
);
const ReviewRow = ({ label, value, mono, children }) => (
  <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr', padding: '12px 0', borderBottom: `1px dashed ${T.border1}`, alignItems: 'baseline' }}>
    <div style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.08em', color: T.fg3 }}>— {label}</div>
    <div style={{ fontFamily: mono ? fontMono : fontSans, fontSize: 13, color: T.fg1 }}>{children || value || '—'}</div>
  </div>
);

// ====================== Mount on canvas ======================
function App() {
  return (
    <DesignCanvas title="Tag Registry — redesigned" subtitle="Sendout Validator design system · light scheme · teal #0fb5b5">
      <DCSection id="redesigns" title="Selected direction">
        <DCArtboard id="a" label="A · Console · sectioned form with HUD-framed active rules" width={1180} height={820}>
          <DirectionA/>
        </DCArtboard>
      </DCSection>
    </DesignCanvas>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
