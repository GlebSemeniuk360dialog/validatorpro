// src/mobile-screens.jsx — every screen in the mobile Validator Pro prototype.

const { useState: useStateMS } = React;
const T2 = window.tokens;

// ─────────────────────────────────────────────────────────────────────
// LOGIN
// ─────────────────────────────────────────────────────────────────────
function LoginScreen({ onSignIn }) {
  const [u, setU] = useStateMS('');
  const [p, setP] = useStateMS('');
  const [err, setErr] = useStateMS('');
  const today = '2026-05-15';

  const submit = () => {
    const valid = { gleb: 'Gleb Semeniuk', martina: 'Martina Sesar', alex: 'Alex Volkonitin' };
    if (valid[u.toLowerCase()] && p) { setErr(''); onSignIn(valid[u.toLowerCase()]); }
    else setErr('Invalid credentials · 4 attempt(s) remaining');
  };

  return (
    <div style={{
      width: '100%', height: '100%', background: T2.bg.app,
      padding: '24px 20px 40px', boxSizing: 'border-box',
      display: 'flex', flexDirection: 'column', gap: 18, overflow: 'auto',
      fontFamily: T2.font.sans,
    }}>
      {/* Top label rail */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        fontFamily: T2.font.mono, fontSize: 9, letterSpacing: '0.18em',
        textTransform: 'uppercase', color: T2.accent.base,
      }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
          <MLed kind="accent" pulse /> Secure terminal
        </span>
        <span style={{ color: T2.fg[4] }}>{today}</span>
      </div>

      {/* HUD panel */}
      <div style={{
        position: 'relative', background: T2.bg.surface1,
        border: `1px solid ${T2.border.base}`, borderRadius: 6,
        padding: '22px 18px', marginTop: 4,
      }}>
        <MCorners />

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
          <img src="assets/validator-mark.svg" alt="" style={{ width: 44, height: 44, borderRadius: 4, display: 'block' }} />
          <div>
            <div style={{ fontFamily: T2.font.display, fontWeight: 600, fontSize: 20, color: T2.fg[1], letterSpacing: '-0.01em' }}>Validator Pro</div>
            <div style={{ fontFamily: T2.font.mono, fontSize: 9, letterSpacing: '0.16em', textTransform: 'uppercase', color: T2.fg[3], marginTop: 2 }}>
              360dialog · sendout audit
            </div>
          </div>
        </div>

        <hr style={{ border: 'none', borderTop: `1px dashed ${T2.border.hud}`, margin: '0 0 16px' }} />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <MOverline style={{ marginBottom: 6 }}>— Operator</MOverline>
            <MInput value={u} onChange={setU} placeholder="gleb / martina / alex" />
          </div>
          <div>
            <MOverline style={{ marginBottom: 6 }}>— Passphrase</MOverline>
            <MInput value={p} onChange={setP} type="password" placeholder="••••••••" />
          </div>
          {err && (
            <div style={{
              padding: '9px 12px', borderRadius: 4,
              background: T2.danger.soft2, border: `1px solid ${T2.danger.ring}`,
              color: T2.danger.base, fontSize: 11, fontFamily: T2.font.mono,
              letterSpacing: '0.04em', display: 'flex', alignItems: 'center', gap: 8,
            }}><MLed kind="danger" pulse /> {err}</div>
          )}
          <MButton onClick={submit} fullWidth size="lg" style={{ marginTop: 4 }}>Sign in →</MButton>
        </div>

        <hr style={{ border: 'none', borderTop: `1px dashed ${T2.border.hud}`, margin: '18px 0 12px' }} />

        <div style={{ fontFamily: T2.font.mono, fontSize: 9, color: T2.fg[4], lineHeight: 1.9, letterSpacing: '0.06em' }}>
          <div>LOCKOUT&nbsp;·&nbsp;<span style={{ color: T2.fg[3] }}>5 attempts / 300s</span></div>
          <div>AUDIT&nbsp;·&nbsp;writes to <code style={{ background: T2.bg.surface3, padding: '1px 5px', borderRadius: 2, color: T2.fg[2] }}>audit.log</code></div>
          <div>BUILD&nbsp;·&nbsp;<span style={{ color: T2.accent.base }}>2026.05.14-stable</span></div>
        </div>
      </div>

      <div style={{
        textAlign: 'center', fontFamily: T2.font.mono, fontSize: 9,
        letterSpacing: '0.16em', textTransform: 'uppercase', color: T2.fg[4],
        marginTop: 'auto',
      }}>
        — operators only · 3 active session limit —
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// QUEUE  (default Validator tab — pending tickets, client + date + countdown)
// ─────────────────────────────────────────────────────────────────────
function QueueScreen({ density, onOpen, selected, setSelected }) {
  const [search, setSearch] = useStateMS('');
  const [clientFilter, setClientFilter] = useStateMS('All');
  const clients = ['All', ...new Set(QUEUE_ROWS.map(r => r.client))];

  const filtered = QUEUE_ROWS.filter(r => {
    if (clientFilter !== 'All' && r.client !== clientFilter) return false;
    if (!search) return true;
    const q = search.toLowerCase();
    return r.key.toLowerCase().includes(q) || r.summary.toLowerCase().includes(q) || r.client.toLowerCase().includes(q);
  });

  const selectedKeys = [...selected];
  const multi = selectedKeys.length > 1;

  const toggleSel = (k, e) => {
    e.stopPropagation();
    const next = new Set(selected);
    if (next.has(k)) next.delete(k); else next.add(k);
    setSelected(next);
  };

  const rowPad = density === 'compact' ? '10px 12px' : '14px 14px';
  const rowGap = density === 'compact' ? 6 : 10;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Search + filter chips */}
      <MInput value={search} onChange={setSearch} placeholder="ticket key, client…" icon="⌕" />
      <div style={{
        display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 2,
        scrollbarWidth: 'none', msOverflowStyle: 'none',
      }}>
        {clients.map(c => {
          const active = c === clientFilter;
          return (
            <button key={c} onClick={() => setClientFilter(c)} style={{
              flexShrink: 0, padding: '6px 12px', borderRadius: 999,
              background: active ? T2.brand.base : T2.bg.surface1,
              color: active ? '#fff' : T2.fg[2],
              border: `1px solid ${active ? T2.brand.base : T2.border.input}`,
              fontFamily: T2.font.sans, fontSize: 12, fontWeight: 500,
              cursor: 'pointer', whiteSpace: 'nowrap',
            }}>{c}</button>
          );
        })}
      </div>

      {/* Header strip */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '4px 2px',
      }}>
        <span style={{ fontFamily: T2.font.sans, fontSize: 13, color: T2.fg[1], fontWeight: 600 }}>
          Pending <span style={{ color: T2.brand.text }}>{filtered.length}</span>
        </span>
        <span style={{ fontFamily: T2.font.mono, fontSize: 9, letterSpacing: '0.14em', textTransform: 'uppercase', color: T2.fg[3] }}>
          tap to open · long-press multi
        </span>
      </div>

      {/* Ticket cards */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {filtered.map(r => {
          const isSel = selected.has(r.key);
          const days = daysUntil(r.date);
          const dayColor = days <= 2 ? T2.danger.base : days <= 4 ? T2.warn.base : T2.fg[2];
          return (
            <div key={r.key}
              onClick={() => {
                if (multi || isSel) toggleSel(r.key, { stopPropagation(){} });
                else onOpen(r);
              }}
              onContextMenu={(e) => { e.preventDefault(); toggleSel(r.key, e); }}
              style={{
                position: 'relative',
                background: isSel ? T2.brand.soft : T2.bg.surface1,
                border: `1px solid ${isSel ? T2.brand.ring : T2.border.base}`,
                borderRadius: 6, padding: rowPad, cursor: 'pointer',
                display: 'flex', flexDirection: 'column', gap: rowGap,
              }}>
              {/* Top row: client + status + check */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <MLed kind={r.priority === 'high' ? 'danger' : r.priority === 'med' ? 'warn' : 'dim'} pulse={r.priority === 'high'} />
                <span style={{ fontSize: 13, fontWeight: 600, color: T2.fg[1], flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {r.client}
                </span>
                <MBadge kind={r.status === 'In Progress' ? 'warn' : 'info'} style={{ flexShrink: 0 }}>
                  {r.status}
                </MBadge>
              </div>
              {/* Summary */}
              <div style={{
                fontSize: 12, color: T2.fg[2], lineHeight: 1.4,
                display: '-webkit-box', WebkitLineClamp: density === 'compact' ? 1 : 2,
                WebkitBoxOrient: 'vertical', overflow: 'hidden',
              }}>{r.summary}</div>
              {/* Bottom row: key · date · countdown */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 2 }}>
                <span style={{
                  fontFamily: T2.font.mono, fontSize: 10, color: T2.fg[3],
                  letterSpacing: '0.04em',
                }}>{r.key}</span>
                <span style={{ color: T2.fg[4], fontSize: 10 }}>·</span>
                <span style={{ fontFamily: T2.font.mono, fontSize: 10, color: T2.fg[3] }}>{r.date}</span>
                <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  <span style={{
                    fontFamily: T2.font.mono, fontSize: 9, letterSpacing: '0.14em',
                    textTransform: 'uppercase', color: T2.fg[4],
                  }}>T-</span>
                  <span style={{
                    fontFamily: T2.font.mono, fontSize: 13, fontWeight: 600,
                    color: dayColor, letterSpacing: '0.02em',
                    fontVariantNumeric: 'tabular-nums',
                  }}>{days < 0 ? `+${Math.abs(days)}` : days}d</span>
                </span>
              </div>
              {isSel && <MCorners color={T2.brand.base} />}
            </div>
          );
        })}
      </div>

      {/* Bulk action bar */}
      {multi && (
        <div style={{
          position: 'sticky', bottom: 0,
          background: T2.bg.surface1, border: `1px solid ${T2.brand.ring}`,
          borderRadius: 6, padding: '10px 12px',
          display: 'flex', flexDirection: 'column', gap: 8,
          boxShadow: '0 -4px 12px rgba(15, 24, 40, 0.06)',
        }}>
          <div style={{ fontSize: 12, color: T2.fg[1] }}>
            <strong>{selectedKeys.length}</strong> tickets selected
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <MButton size="sm" style={{ flex: 1 }}>⚡ Bulk Check</MButton>
            <MButton variant="ghost" size="sm" style={{ flex: 1 }}>🤖 AI Audit</MButton>
            <MButton variant="ghost" size="sm" onClick={() => setSelected(new Set())}>✕</MButton>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// VALIDATOR drilldown — Setup / Content / Visuals / AI segmented sub-nav
// ─────────────────────────────────────────────────────────────────────
function ValidatorScreen({ ticket, onBack }) {
  const [tab, setTab] = useStateMS('Setup');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* HUD record header */}
      <div style={{
        position: 'relative', background: T2.bg.surface1,
        border: `1px solid ${T2.border.base}`, borderRadius: 6, padding: '12px 14px',
      }}>
        <MCorners />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <button onClick={onBack} style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            fontFamily: T2.font.sans, fontSize: 13, color: T2.brand.text,
            display: 'inline-flex', alignItems: 'center', gap: 4, padding: 0,
          }}>← Queue</button>
          <span style={{ marginLeft: 'auto' }}><MBracket>LIVE</MBracket></span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <MLed kind="accent" pulse />
          <span style={{
            fontFamily: T2.font.mono, fontSize: 13, color: T2.fg[1],
            letterSpacing: '0.04em', fontWeight: 600,
          }}>{ticket.key}</span>
        </div>
        <div style={{ marginTop: 4, fontSize: 12, color: T2.fg[2], lineHeight: 1.4 }}>
          {ticket.summary}
        </div>
        <div style={{
          marginTop: 8, display: 'flex', gap: 8, fontFamily: T2.font.mono,
          fontSize: 10, color: T2.fg[3], letterSpacing: '0.04em', flexWrap: 'wrap',
        }}>
          <span>{ticket.client}</span>
          <span style={{ color: T2.fg[4] }}>·</span>
          <span>{ticket.date}T09:45Z</span>
          <span style={{ color: T2.fg[4] }}>·</span>
          <span>T-{daysUntil(ticket.date)}d</span>
        </div>
        <div style={{ display: 'flex', gap: 6, marginTop: 12 }}>
          <MButton size="sm" variant="ghost" style={{ flex: 1 }}>⚡ Regular</MButton>
          <MButton size="sm" style={{ flex: 1 }}>🤖 AI Audit</MButton>
        </div>
      </div>

      {/* Segmented sub-nav */}
      <SegmentedSubNav tabs={['Setup', 'Content', 'Visuals', 'AI']} active={tab} onChange={setTab} />

      {tab === 'Setup'   && <SetupPanelM   ticket={ticket} />}
      {tab === 'Content' && <ContentPanelM ticket={ticket} />}
      {tab === 'Visuals' && <VisualsPanelM ticket={ticket} />}
      {tab === 'AI'      && <AIPanelM      ticket={ticket} />}
    </div>
  );
}

function SegmentedSubNav({ tabs, active, onChange }) {
  return (
    <div style={{
      display: 'flex', gap: 3,
      background: T2.bg.surface3, padding: 3, borderRadius: 6,
      border: `1px solid ${T2.border.base}`,
    }}>
      {tabs.map(t => {
        const a = active === t;
        return (
          <button key={t} onClick={() => onChange(t)} style={{
            flex: 1, padding: '8px 6px', borderRadius: 4, border: 'none',
            background: a ? T2.brand.base : 'transparent',
            color: a ? '#fff' : T2.fg[2],
            fontFamily: T2.font.sans, fontSize: 12, fontWeight: 600,
            cursor: 'pointer', transition: 'all .18s',
            boxShadow: a ? T2.brand.glowSm : 'none',
          }}>{t}</button>
        );
      })}
    </div>
  );
}

// ── SETUP ─────────────────────────────────────────────────────────────
function SetupPanelM({ ticket }) {
  return (
    <div>
      <MSectionHeader style={{ marginTop: 4 }}>Control panel</MSectionHeader>
      <MCard>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Field label="🎯 Client context" value={ticket.client} />
          <Field label="🎫 Ticket ID"      value={ticket.key} mono />
          <Field label="📅 G-Sheet row"    value={`${ticket.date} · Task #${ticket.key}`} />
          <Field label="Sendout ID"         value="9b3f-8e8c-2c4f-aaaa" mono />
        </div>
      </MCard>
      <MSectionHeader>Pre-flight checks</MSectionHeader>
      <MCheckRow kind="ok"   label="JIRA fetch"     value="200 OK · description, footer, CTA loaded" />
      <MCheckRow kind="ok"   label="DMA fetch"      value={`account_id=7 · scheduled=${ticket.date}`} />
      <MCheckRow kind="ok"   label="Template fetch" value="waba-v2.360dialog.io · template loaded" />
      <MCheckRow kind="warn" label="Ticket changed" value="Description differs (+18 / -4 chars) — re-run audit recommended" />
    </div>
  );
}

function Field({ label, value, mono }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ fontSize: 11, color: T2.fg[3] }}>{label}</div>
      <div style={{
        padding: '9px 11px', background: T2.bg.surface2,
        border: `1px solid ${T2.border.input}`, borderRadius: 4,
        fontFamily: mono ? T2.font.mono : T2.font.sans,
        fontSize: 12, color: T2.fg[1], letterSpacing: mono ? '0.02em' : 0,
        wordBreak: 'break-all',
      }}>{value}</div>
    </div>
  );
}

// ── CONTENT ───────────────────────────────────────────────────────────
function ContentPanelM({ ticket }) {
  const [showDiff, setShowDiff] = useStateMS(false);
  const jira = `Hallo {{1}}, hier sind die neuesten Angebote für deine Filiale in {{shop_city}}. Gültig vom {{leaflet_start_date}} bis {{leaflet_end_date}}.`;
  const tmpl = `Hallo {{1}}, hier sind die neuesten Angebote für deine Filiale in {{shop_city}} {{shop_address}}. Gültig vom {{leaflet_start_date}} bis {{leaflet_end_date}}.`;
  return (
    <div>
      <MSectionHeader style={{ marginTop: 4 }}>Text comparison</MSectionHeader>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <MCard title="— JIRA description">
          <pre style={preStyleM}>{jira}</pre>
        </MCard>
        <MCard title="— Template body">
          <pre style={preStyleM}>{tmpl}</pre>
        </MCard>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <MBadge kind="warn">Similarity 94%</MBadge>
          <button onClick={() => setShowDiff(d => !d)} style={{
            marginLeft: 'auto', background: 'transparent',
            border: `1px solid ${T2.border.input}`, color: T2.fg[2],
            padding: '5px 10px', fontSize: 11, borderRadius: 3, cursor: 'pointer',
            fontFamily: T2.font.sans,
          }}>{showDiff ? 'Hide diff' : 'Show diff'}</button>
        </div>
        {showDiff && (
          <div style={{
            background: T2.bg.appSoft, border: `1px solid ${T2.border.base}`,
            borderRadius: 4, padding: 10,
          }}>
            <div style={{
              fontFamily: T2.font.mono, fontSize: 10, padding: '2px 6px',
              background: T2.danger.soft, color: T2.danger.base, borderRadius: 2,
              marginBottom: 3, whiteSpace: 'pre-wrap',
            }}>- {`{{shop_city}}`}. Gültig…</div>
            <div style={{
              fontFamily: T2.font.mono, fontSize: 10, padding: '2px 6px',
              background: T2.ok.soft, color: T2.ok.base, borderRadius: 2,
              whiteSpace: 'pre-wrap',
            }}>+ {`{{shop_city}} {{shop_address}}`}. Gültig…</div>
          </div>
        )}
      </div>

      <MSectionHeader>Interactive elements</MSectionHeader>
      <MCheckRow kind="ok"   label="Footer"     value="JIRA / API match" />
      <MCheckRow kind="fail" label="CTA Button" value='"Zum Prospekt" not in API set ["Mehr erfahren", "Abmelden"]' />

      <MSectionHeader>URL validation</MSectionHeader>
      <MOverline style={{ marginBottom: 5 }}>— Expected (JIRA)</MOverline>
      <MUrlRow icon="✅" url="https://aldi-sued.de/de/angebote/aktion.html?utm=wapp" kind="ok" />
      <MUrlRow icon="❌" url="https://aldi-sued.de/de/prospekt/2026-10-17.html" kind="danger" />
      <MOverline style={{ marginBottom: 5, marginTop: 10 }}>— Actual (API)</MOverline>
      <MUrlRow icon="🔗" url="https://aldi-sued.de/de/angebote/aktion.html?utm=wapp" />
      <MUrlRow icon="🔗" url="https://aldi-sued.de/de/prospekt/2026-10-17-living.html" />
      <MUrlRow icon="🔗" url="https://wa.me/421940123456?text=stop" />
    </div>
  );
}

const preStyleM = {
  fontFamily: T2.font.mono, fontSize: 11, color: T2.fg[1],
  whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0, lineHeight: 1.6,
};

// ── VISUALS ───────────────────────────────────────────────────────────
function VisualsPanelM({ ticket }) {
  const [open, setOpen] = useStateMS(1);
  const slides = [
    { num: 1, body: 'Hier findest du unsere Angebote für die kommende Woche ⬇️', button: 'Zum Prospekt' },
    { num: 2, body: 'Frische Obst- und Gemüse-Aktionen — gültig ab Donnerstag.', button: 'Jetzt entdecken' },
    { num: 3, body: 'Wohnen & Garten — neue Wochenangebote.', button: 'Zum Prospekt' },
  ];
  return (
    <div>
      <MSectionHeader style={{ marginTop: 4 }}>Carousel slides</MSectionHeader>
      {slides.map(s => {
        const isOpen = open === s.num;
        return (
          <div key={s.num} style={{
            background: T2.bg.surface1, border: `1px solid ${T2.border.base}`,
            borderRadius: 6, marginBottom: 8, overflow: 'hidden',
          }}>
            <div onClick={() => setOpen(isOpen ? 0 : s.num)} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '12px 14px', cursor: 'pointer',
            }}>
              <span style={{
                fontSize: 14, color: T2.fg[3],
                transition: 'transform .2s', display: 'inline-block',
                transform: isOpen ? 'rotate(90deg)' : 'rotate(0)',
              }}>›</span>
              <span style={{
                fontFamily: T2.font.mono, fontSize: 10, fontWeight: 600,
                textTransform: 'uppercase', letterSpacing: '0.14em',
                color: T2.brand.slide,
              }}>Slide {s.num}</span>
              <span style={{ marginLeft: 'auto' }}>
                <MBadge kind={s.num === 1 ? 'ok' : 'neutral'}>{s.num === 1 ? 'match' : 'pending'}</MBadge>
              </span>
            </div>
            {isOpen && (
              <div style={{ padding: '0 14px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                <SidebySideImg num={s.num} source="JIRA" body={s.body} button={s.button} />
                <SidebySideImg num={s.num} source="DMA configured" body={s.body} button={s.button} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function SidebySideImg({ num, source, body, button }) {
  return (
    <div style={{
      background: T2.bg.surface2, border: `1px solid ${T2.border.base}`,
      borderRadius: 6, overflow: 'hidden',
    }}>
      <div style={{
        height: 100, background: T2.bg.appSoft,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: T2.fg[4], fontSize: 10, fontFamily: T2.font.mono,
        backgroundImage: `repeating-linear-gradient(45deg, ${T2.border.base} 0 1px, transparent 1px 11px)`,
      }}>
        {source === 'JIRA' ? 'jira_carousel_' : 'dma_template_'}{`0${num}.png`}
      </div>
      <div style={{
        padding: '6px 10px', fontFamily: T2.font.mono, fontSize: 9,
        letterSpacing: '0.14em', textTransform: 'uppercase', color: T2.fg[3],
        borderTop: `1px solid ${T2.border.base}`,
      }}>{source}</div>
      <div style={{ padding: '4px 10px 10px', fontSize: 11, color: T2.fg[1], lineHeight: 1.5 }}>
        <div style={{ color: T2.fg[3], fontSize: 10, marginBottom: 2 }}>BODY</div>
        <div>{body}</div>
        <div style={{ color: T2.fg[3], fontSize: 10, marginTop: 4, marginBottom: 2 }}>BUTTON</div>
        <div style={{ fontFamily: T2.font.mono, fontSize: 11, color: T2.brand.text }}>{button}</div>
      </div>
    </div>
  );
}

// ── AI ────────────────────────────────────────────────────────────────
function AIPanelM({ ticket }) {
  return (
    <div>
      <MSectionHeader style={{ marginTop: 4 }}>AI Audit · gemini-2.5-pro</MSectionHeader>
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <MBadge kind="danger">2 issues found</MBadge>
        <MBadge kind="neutral">⏱ 2.4s</MBadge>
        <MBadge kind="neutral">⊝ 4 sections</MBadge>
      </div>

      <div style={{
        background: T2.bg.surface1, border: `1px solid ${T2.danger.ring}`,
        borderRadius: 6, padding: '12px 14px',
        fontSize: 12, lineHeight: 1.7, color: T2.fg[1],
      }}>
        <H3M>Body comparison</H3M>
        <LiM><PassM/> Greeting matches JIRA.</LiM>
        <LiM><PassM/> Date placeholders match: <CodeM>{'{{leaflet_start_date}}'}</CodeM>.</LiM>
        <LiM><FailM/> Footer line missing — <EmM>JIRA: "Hier bin ich richtig" / API: "(empty)"</EmM>.</LiM>

        <H3M>CTA</H3M>
        <LiM><FailM/> Button mismatch: <StrM>"Zum Prospekt"</StrM> not in API set <CodeM>["Mehr erfahren"]</CodeM>.</LiM>

        <H3M>Audience filters</H3M>
        <LiM><PassM/> All required include filters present.</LiM>
        <LiM><PassM/> No unexpected exclude filters.</LiM>

        <H3M>Recommendation</H3M>
        <LiM>Update DMA template buttons to include <CodeM>"Zum Prospekt"</CodeM> before approving.</LiM>
      </div>

      <div style={{ display: 'flex', gap: 6, marginTop: 12 }}>
        <MButton size="md" variant="ghost" style={{ flex: 1 }}>Retry</MButton>
        <MButton size="md" variant="danger" style={{ flex: 1 }}>Reject</MButton>
        <MButton size="md" variant="primary" style={{ flex: 1 }}>Approve</MButton>
      </div>
    </div>
  );
}

const H3M  = ({ children }) => <div style={{ fontFamily: T2.font.mono, fontSize: 10, fontWeight: 600, color: T2.brand.text, textTransform: 'uppercase', letterSpacing: '0.12em', margin: '12px 0 4px' }}>— {children}</div>;
const LiM   = ({ children }) => <div style={{ padding: '2px 0 2px 8px', lineHeight: 1.6, fontSize: 12 }}>{children}</div>;
const PassM = () => <span style={{ color: T2.ok.base, fontWeight: 700, marginRight: 4 }}>✓</span>;
const FailM = () => <span style={{ color: T2.danger.base, fontWeight: 700, marginRight: 4 }}>✕</span>;
const CodeM = ({ children }) => <code style={{ background: T2.bg.surface3, padding: '1px 5px', borderRadius: 3, fontFamily: T2.font.mono, fontSize: 10, color: T2.fg[1] }}>{children}</code>;
const EmM   = ({ children }) => <em style={{ color: T2.fg[2], fontStyle: 'italic' }}>{children}</em>;
const StrM  = ({ children }) => <strong style={{ color: T2.fg[1], fontWeight: 600 }}>{children}</strong>;

// ─────────────────────────────────────────────────────────────────────
// ORPHAN SCANNER
// ─────────────────────────────────────────────────────────────────────
function OrphansScreen() {
  const [scanned, setScanned] = useStateMS(true);
  const noJira   = ORPHANS.filter(r => r.status === 'no_jira');
  const noSheet  = ORPHANS.filter(r => r.status === 'no_gsheet');
  const auto     = ORPHANS.filter(r => r.status === 'auto');
  const orphans  = noJira.length + noSheet.length;

  if (!scanned) {
    return (
      <div>
        <MSectionHeader style={{ marginTop: 4 }}>⚠️ Orphan Sendout Scanner</MSectionHeader>
        <div style={{ fontSize: 12, color: T2.fg[2], lineHeight: 1.6, marginBottom: 14 }}>
          Finds DMA sendouts that have no matching JIRA ticket or G-Sheet row.
        </div>
        <MButton onClick={() => setScanned(true)} fullWidth size="lg">▶ Scan all accounts</MButton>
      </div>
    );
  }

  return (
    <div>
      <MSectionHeader style={{ marginTop: 4 }}>Orphan scan · {ORPHANS.length} sendouts</MSectionHeader>
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6,
        background: T2.bg.surface1, border: `1px solid ${T2.border.base}`,
        borderRadius: 6, padding: '12px 12px',
      }}>
        <MReadout label="total" value={ORPHANS.length} size={20} />
        <MReadout label="matched" value={ORPHANS.length - orphans - auto.length} valueKind="ok" size={20} />
        <MReadout label="orphans" value={orphans} valueKind="danger" size={20} />
      </div>

      <div style={{
        marginTop: 10, padding: '8px 12px',
        background: T2.info.soft, border: `1px solid ${T2.info.ring}`,
        borderRadius: 4, fontSize: 11, color: T2.brand.text, lineHeight: 1.4,
      }}>🔵 {auto.length} automated sendout(s) excluded — no JIRA required.</div>

      <OrphanGroup icon="🔴" label="Missing from JIRA queue" rows={noJira}  defaultOpen />
      <OrphanGroup icon="🟡" label="Missing from G-Sheet"     rows={noSheet} defaultOpen />
      <OrphanGroup icon="🔵" label="Automated"                rows={auto}    />
    </div>
  );
}

function OrphanGroup({ icon, label, rows, defaultOpen }) {
  const [open, setOpen] = useStateMS(!!defaultOpen);
  if (!rows.length) return null;
  return (
    <div style={{ marginTop: 18 }}>
      <div onClick={() => setOpen(o => !o)} style={{
        cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 0',
      }}>
        <span style={{
          fontSize: 12, color: T2.fg[3], display: 'inline-block',
          transform: open ? 'rotate(90deg)' : 'rotate(0)', transition: 'transform .2s',
        }}>›</span>
        <span style={{ fontSize: 13 }}>{icon}</span>
        <span style={{ fontSize: 13, color: T2.fg[1], fontWeight: 600 }}>{label}</span>
        <span style={{ marginLeft: 'auto', fontFamily: T2.font.mono, fontSize: 10, color: T2.fg[3] }}>({rows.length})</span>
      </div>
      {open && rows.map((r, i) => (
        <div key={i} style={{
          background: T2.bg.surface1, border: `1px solid ${T2.border.base}`,
          borderRadius: 6, padding: '12px 14px', marginBottom: 8,
          display: 'flex', flexDirection: 'column', gap: 6,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 13, color: T2.fg[1], fontWeight: 600, flex: 1 }}>{r.client}</span>
            <MBadge kind={r.status === 'no_jira' ? 'danger' : r.status === 'no_gsheet' ? 'warn' : 'info'}>
              {r.status === 'no_jira' ? 'no JIRA' : r.status === 'no_gsheet' ? 'no G-Sheet' : 'auto'}
            </MBadge>
          </div>
          <div style={{ fontSize: 12, color: T2.fg[2], lineHeight: 1.4 }}>{r.name}</div>
          <div style={{
            display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
            fontFamily: T2.font.mono, fontSize: 10, color: T2.fg[3],
            letterSpacing: '0.04em',
          }}>
            <span>{r.date}</span>
            <span style={{ color: T2.fg[4] }}>·</span>
            <code style={{
              background: T2.bg.surface3, padding: '1px 5px', borderRadius: 2,
              color: T2.fg[2], fontSize: 10,
            }}>{r.id}</code>
          </div>
          {r.status === 'no_jira' && (
            <div style={{
              marginTop: 4, padding: '8px 10px', borderRadius: 3,
              background: T2.warn.soft, border: `1px solid ${T2.warn.ring}`,
              color: T2.fg[1], fontSize: 11, lineHeight: 1.5,
            }}>⚠️ No matching JIRA ticket. May have been created directly in DMA.</div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// DASHBOARD
// ─────────────────────────────────────────────────────────────────────
function DashboardScreen() {
  return (
    <div>
      <MSectionHeader style={{ marginTop: 4 }}>Today</MSectionHeader>
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8,
      }}>
        <MCard><MReadout label="validations" value="24" sub="▲ +6 vs yesterday" subKind="ok" /></MCard>
        <MCard><MReadout label="pass rate"   value="83%" valueKind="ok" sub="20 / 24" /></MCard>
        <MCard><MReadout label="avg audit"   value={<span>2.4<span style={{color:T2.fg[3], fontSize: 11}}>s</span></span>} valueKind="accent" sub="gemini-2.5-pro" subKind="accent" /></MCard>
        <MCard><MReadout label="alerts"      value="03" valueKind="danger" sub="▼ last 1h" subKind="danger" /></MCard>
      </div>

      <MSectionHeader>Top failure modes · 7d</MSectionHeader>
      <MCard padding="12px 14px">
        {[
          ['CTA button mismatch', 9, 1.0],
          ['Footer text missing', 5, 0.55],
          ['URL placeholder unfilled', 4, 0.44],
          ['Carousel slide order', 2, 0.22],
          ['Wrong leaflet_type tag', 2, 0.22],
        ].map(([label, count, frac], i) => (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: i < 4 ? 10 : 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
              <span style={{ color: T2.fg[1] }}>{label}</span>
              <span style={{ fontFamily: T2.font.mono, color: T2.danger.base, fontWeight: 600 }}>{count}</span>
            </div>
            <div style={{ height: 4, background: T2.bg.surface3, borderRadius: 2, overflow: 'hidden' }}>
              <div style={{ width: `${frac*100}%`, height: '100%', background: T2.danger.base, opacity: 0.65 }} />
            </div>
          </div>
        ))}
      </MCard>

      <MSectionHeader>Audit log</MSectionHeader>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {LOG.map((l, i) => {
          const dot = ({ ok: T2.ok.base, danger: T2.danger.base, warn: T2.warn.base, info: T2.brand.text }[l.kind]);
          return (
            <div key={i} style={{
              background: T2.bg.surface1, border: `1px solid ${T2.border.base}`,
              borderRadius: 4, padding: '8px 10px',
              display: 'flex', alignItems: 'center', gap: 10,
            }}>
              <span style={{
                width: 6, height: 6, borderRadius: '50%', background: dot,
                flexShrink: 0,
              }} />
              <span style={{ fontFamily: T2.font.mono, fontSize: 10, color: T2.fg[3], width: 36 }}>{l.ts}</span>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontFamily: T2.font.mono, fontSize: 10, color: T2.fg[1], fontWeight: 600, letterSpacing: '0.04em' }}>
                  {l.action} <span style={{ color: T2.fg[3], fontWeight: 400 }}>· {l.user}</span>
                </div>
                {l.detail && <div style={{ fontSize: 11, color: T2.fg[2], marginTop: 1 }}>{l.detail}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// PROFILE / SESSION (the desktop sidebar, mobilized)
// ─────────────────────────────────────────────────────────────────────
function ProfileScreen({ user, onSignOut }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Identity */}
      <div style={{
        position: 'relative', background: T2.bg.surface1,
        border: `1px solid ${T2.border.base}`, borderRadius: 6,
        padding: '16px 14px',
      }}>
        <MCorners />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 40, height: 40, borderRadius: 4,
            background: T2.brand.dark, color: '#fff',
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: T2.font.display, fontWeight: 700, fontSize: 16,
          }}>{(user || 'G').split(' ').map(s => s[0]).slice(0, 2).join('')}</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: T2.fg[1] }}>{user}</div>
            <div style={{
              fontFamily: T2.font.mono, fontSize: 10, color: T2.fg[3],
              letterSpacing: '0.12em', textTransform: 'uppercase', marginTop: 1,
              display: 'inline-flex', alignItems: 'center', gap: 6,
            }}><MLed kind="ok" pulse size={6} /> active session</div>
          </div>
        </div>
      </div>

      <MSectionHeader style={{ marginTop: 4 }}>Connections</MSectionHeader>
      <MCard padding="12px 14px">
        {CONNECTIONS.map((c, i) => (
          <div key={c.label} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            padding: '8px 0',
            borderBottom: i < CONNECTIONS.length - 1 ? `1px dashed ${T2.border.base}` : 'none',
          }}>
            <MLed kind={c.led} pulse={c.led === 'ok' || c.led === 'warn'} />
            <span style={{ fontFamily: T2.font.mono, fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase', color: T2.fg[2] }}>{c.label}</span>
            <span style={{ marginLeft: 'auto', fontFamily: T2.font.mono, fontSize: 10, color: T2.fg[3] }}>{c.meta}</span>
          </div>
        ))}
      </MCard>

      <MSectionHeader>Tools</MSectionHeader>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <RowBtn label="🔄 Refresh G-Sheet" />
        <RowBtn label="🧹 Clear cache" />
        <RowBtn label="🔍 JIRA Field Inspector" trailing="off" />
        <RowBtn label="📡 Slack webhook" trailing="idle" />
      </div>

      <MSectionHeader>Session</MSectionHeader>
      <MCard padding="12px 14px">
        <div style={{ fontFamily: T2.font.mono, fontSize: 10, color: T2.fg[3], letterSpacing: '0.08em', lineHeight: 1.9 }}>
          <div>SESSION&nbsp;·&nbsp;<span style={{ color: T2.accent.base }}>432.7s</span></div>
          <div>BUILD&nbsp;·&nbsp;<span style={{ color: T2.fg[2] }}>2026.05.14-stable</span></div>
          <div>DEVICE&nbsp;·&nbsp;<span style={{ color: T2.fg[2] }}>mobime · ios</span></div>
        </div>
      </MCard>

      <MButton variant="danger" fullWidth size="md" onClick={onSignOut} style={{ marginTop: 4 }}>Sign out</MButton>

      <div style={{
        textAlign: 'center', fontFamily: T2.font.mono, fontSize: 9,
        letterSpacing: '0.16em', textTransform: 'uppercase', color: T2.fg[4],
        marginTop: 4,
      }}>— 360dialog · ops · v1.0 —</div>
    </div>
  );
}

function RowBtn({ label, trailing }) {
  return (
    <div style={{
      background: T2.bg.surface1, border: `1px solid ${T2.border.base}`,
      borderRadius: 4, padding: '12px 14px',
      display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
      fontSize: 13, color: T2.fg[1],
    }}>
      <span style={{ flex: 1 }}>{label}</span>
      {trailing && <span style={{ fontFamily: T2.font.mono, fontSize: 10, color: T2.fg[3], letterSpacing: '0.12em', textTransform: 'uppercase' }}>{trailing}</span>}
      <span style={{ color: T2.fg[4], fontSize: 16 }}>›</span>
    </div>
  );
}

Object.assign(window, {
  LoginScreen, QueueScreen, ValidatorScreen, OrphansScreen, DashboardScreen, ProfileScreen,
});
