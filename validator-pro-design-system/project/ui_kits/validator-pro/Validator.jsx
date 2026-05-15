// ui_kits/validator-pro/Validator.jsx
// The deep validator view shown after a ticket is loaded.
// Sub-nav: Setup · Content · Visuals · AI (matches the .vp-nav structure).
const { useState: useStateV } = React;

function ValidatorPanel({ ticket, onBack }) {
  const [tab, setTab] = useStateV('Setup');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <HudPanel>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <Button variant="ghost" onClick={onBack}>← Back to queue</Button>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            fontFamily: tokens.font.mono, fontSize: 13, color: tokens.fg[2],
          }}>
            <Led kind="accent" pulse />
            <span style={{ color: tokens.fg[1], letterSpacing: '0.04em' }}>{ticket.key}</span>
            <span style={{ color: tokens.fg[4] }}>·</span>
            <span>{ticket.client}</span>
            <span style={{ color: tokens.fg[4] }}>·</span>
            <span style={{ color: tokens.fg[3] }}>{ticket.date}T09:45:36Z</span>
          </div>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
            <Bracket>LIVE</Bracket>
            <Button variant="ghost">⚡ Regular Check</Button>
            <Button>🤖 Run AI Audit</Button>
          </div>
        </div>
      </HudPanel>

      <SubNav active={tab} onChange={setTab} />

      <div style={{ marginTop: 4 }}>
        {tab === 'Setup'   && <SetupPanel   ticket={ticket} />}
        {tab === 'Content' && <ContentPanel ticket={ticket} />}
        {tab === 'Visuals' && <VisualsPanel ticket={ticket} />}
        {tab === 'AI'      && <AIPanel      ticket={ticket} />}
      </div>
    </div>
  );
}

function SubNav({ active, onChange }) {
  const tabs = ['Setup', 'Content', 'Visuals', 'AI'];
  return (
    <div style={{
      position: 'sticky', top: 0, zIndex: 50,
      background: tokens.bg.app, padding: '4px 0',
    }}>
      <div style={{
        display: 'flex', gap: 4, background: tokens.bg.surface1,
        border: `1px solid ${tokens.border.base}`, borderRadius:8, padding: 5,
        maxWidth: 480,
      }}>
        {tabs.map(t => (
          <NavPill key={t} active={active === t} onClick={() => onChange(t)}>{t}</NavPill>
        ))}
      </div>
    </div>
  );
}

// ── SETUP ──────────────────────────────────────────────────────────────
function SetupPanel({ ticket }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <SectionHeader style={{ marginTop: 8 }}>Control panel</SectionHeader>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 2fr', gap: 12 }}>
        <Field label="🎯 Client Context">
          <Select value={ticket.client} options={['ALDI Sued', 'Kaufland RCS', 'PENNY Austria', 'REWE', 'ALDI Portugal']} />
        </Field>
        <Field label="🎫 Ticket ID">
          <Input value={ticket.key} />
        </Field>
        <Field label="📅 G-Sheet row">
          <Select options={[`${ticket.date}  |  Sendout Task #${ticket.key}  |  9b3f-8e8c-2c4f-aaaa`]} />
        </Field>
      </div>
      <Field label="Sendout ID (override)">
        <Input placeholder="Sendout ID auto-detected — override if needed" />
      </Field>
      <div style={{ fontSize: 11, color: tokens.fg[3] }}>
        Sendout found: <code style={{
          fontFamily: tokens.font.mono, background: tokens.bg.surface3,
          padding: '1px 5px', borderRadius: 3, fontSize: 11, color: tokens.fg[2],
        }}>9b3f-8e8c-2c4f-aaaa</code>
      </div>

      <SectionHeader>Pre-flight checks</SectionHeader>
      <CheckRow kind="ok"   label="JIRA fetch"        value="200 OK · description, footer, CTA, custom fields loaded" />
      <CheckRow kind="ok"   label="DMA fetch"         value={`account_id=7 · scheduled_date=${ticket.date} · component_parameters loaded`} />
      <CheckRow kind="ok"   label="Template fetch"    value={`waba-v2.360dialog.io · template_name=prospekt_${ticket.date.replace(/-/g, '')}`} />
      <CheckRow kind="warn" label="Ticket changed since last validation" value="Description text differs (+18 / -4 chars) — re-run audit recommended" />
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label style={{ fontSize: 13, color: tokens.fg[1] }}>{label}</label>
      {children}
    </div>
  );
}

// ── CONTENT ────────────────────────────────────────────────────────────
function ContentPanel({ ticket }) {
  const jira = `Hallo {{1}}, hier sind die neuesten Angebote für deine Filiale in {{shop_city}}. Gültig vom {{leaflet_start_date}} bis {{leaflet_end_date}}.

Viele Grüße
ALDI SÜD - Hier bin ich richtig.`;
  const tmpl = `Hallo {{1}}, hier sind die neuesten Angebote für deine Filiale in {{shop_city}} {{shop_address}}. Gültig vom {{leaflet_start_date}} bis {{leaflet_end_date}}.

Viele Grüße
ALDI SÜD - Hier bin ich richtig.`;

  return (
    <div>
      <SectionHeader style={{ marginTop: 8 }}>Text comparison</SectionHeader>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <Card title="JIRA Description"><pre style={preStyle}>{jira}</pre></Card>
        <Card title="Template Body"><pre style={preStyle}>{tmpl}</pre></Card>
      </div>
      <div style={{ marginTop: 12 }}>
        <Badge kind="warn">Similarity 94%</Badge>
        <DiffToggle from={jira} to={tmpl} />
      </div>

      <SectionHeader>Interactive elements</SectionHeader>
      <CheckRow kind="ok"   label="Footer"     value='JIRA: "Mit freundlichen Grüßen, ALDI Süd" → API: "Mit freundlichen Grüßen, ALDI Süd"' />
      <CheckRow kind="fail" label="CTA Button" value='JIRA: "Zum Prospekt" → API buttons: ["Mehr erfahren", "Abmelden"]' />

      <SectionHeader>URL validation</SectionHeader>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <div>
          <Overline style={{ marginBottom: 8 }}>Expected (JIRA)</Overline>
          <UrlRow icon="✅" url="https://aldi-sued.de/de/angebote/aktion.html?utm=wapp" />
          <UrlRow icon="❌" url="https://aldi-sued.de/de/prospekt/2026-10-17.html" />
        </div>
        <div>
          <Overline style={{ marginBottom: 8 }}>Actual (API)</Overline>
          <UrlRow icon="🔗" url="https://aldi-sued.de/de/angebote/aktion.html?utm=wapp" />
          <UrlRow icon="🔗" url="https://aldi-sued.de/de/prospekt/2026-10-17-living.html" />
          <UrlRow icon="🔗" url="https://wa.me/421940123456?text=stop" />
        </div>
      </div>
    </div>
  );
}

const preStyle = {
  fontFamily: tokens.font.mono, fontSize: 12, color: tokens.fg[1],
  whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0, lineHeight: 1.7,
};

function UrlRow({ icon, url }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '8px 12px', borderRadius:4, marginBottom: 6,
      background: tokens.bg.surface2,
      fontFamily: tokens.font.mono, fontSize: 11, wordBreak: 'break-all',
    }}>
      <span>{icon}</span>
      <a href={url} target="_blank" rel="noreferrer" style={{ color: tokens.ok.base, textDecoration: 'none' }}>{url}</a>
    </div>
  );
}

function DiffToggle({ from, to }) {
  const [open, setOpen] = useStateV(false);
  const lines = diff(from, to);
  return (
    <>
      <Button variant="toggle" onClick={() => setOpen(o => !o)} style={{ marginTop: 10 }}>
        {open ? 'Hide diff' : 'Show diff'}
      </Button>
      {open && (
        <div style={{
          background: tokens.bg.app, border: `1px solid ${tokens.border.base}`,
          borderRadius:4, padding: 12, marginTop: 12,
        }}>
          {lines.map((l, i) => (
            <div key={i} style={{
              fontFamily: tokens.font.mono, fontSize: 11,
              padding: '2px 6px', borderRadius: 3, marginBottom: 1, whiteSpace: 'pre-wrap',
              background: l.kind === 'add' ? tokens.ok.soft : l.kind === 'rem' ? tokens.danger.soft : 'transparent',
              color:      l.kind === 'add' ? tokens.ok.base : l.kind === 'rem' ? tokens.danger.base : tokens.fg[4],
            }}>{l.text}</div>
          ))}
        </div>
      )}
    </>
  );
}

// extremely naive line-by-line diff — good enough for the demo
function diff(a, b) {
  const al = a.split('\n'), bl = b.split('\n');
  const out = [];
  const max = Math.max(al.length, bl.length);
  for (let i = 0; i < max; i++) {
    const x = al[i], y = bl[i];
    if (x === y) out.push({ kind: 'ctx', text: '  ' + (x ?? '') });
    else {
      if (x !== undefined) out.push({ kind: 'rem', text: '- ' + x });
      if (y !== undefined) out.push({ kind: 'add', text: '+ ' + y });
    }
  }
  return out;
}

// ── VISUALS ────────────────────────────────────────────────────────────
function VisualsPanel({ ticket }) {
  return (
    <div>
      <SectionHeader style={{ marginTop: 8 }}>Carousel slides</SectionHeader>
      <SlideAcc num={1} body="Hier findest du unsere Angebote für die kommende Woche ⬇️" button="Zum Prospekt" defaultOpen />
      <SlideAcc num={2} body="Frische Obst- und Gemüse-Aktionen — gültig ab Donnerstag." button="Jetzt entdecken" />
      <SlideAcc num={3} body="Wohnen & Garten — neue Wochenangebote." button="Zum Prospekt" />
    </div>
  );
}

function SlideAcc({ num, body, button, defaultOpen }) {
  const [open, setOpen] = useStateV(!!defaultOpen);
  return (
    <div style={{
      background: tokens.bg.surface1, border: `1px solid ${tokens.border.base}`,
      borderRadius:6, marginBottom: 10, overflow: 'hidden',
    }}>
      <div onClick={() => setOpen(o => !o)} style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '14px 18px', cursor: 'pointer',
        fontSize: 13, fontWeight: 500, color: tokens.fg[1],
      }}>
        <span style={{
          fontSize: 16, color: tokens.fg[3],
          transition: 'transform .2s', display: 'inline-block',
          transform: open ? 'rotate(90deg)' : 'rotate(0)',
        }}>›</span>
        <span style={{
          fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
          letterSpacing: '0.08em', color: tokens.brand.slide,
        }}>Slide {num}</span>
      </div>
      {open && (
        <div style={{
          padding: '14px 18px 18px', borderTop: `1px solid ${tokens.border.base}`,
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14,
        }}>
          <div style={{
            background: tokens.bg.surface2, border: `1px solid ${tokens.border.base}`,
            borderRadius:6, overflow: 'hidden',
          }}>
            <div style={{
              height: 140, background: tokens.bg.app,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: tokens.fg[4], fontSize: 11, fontFamily: tokens.font.mono,
            }}>jira_carousel_image_0{num}.png</div>
            <div style={{ padding: '8px 12px', fontSize: 11, color: tokens.fg[3], fontFamily: tokens.font.mono }}>JIRA</div>
            <div style={{ padding: '0 12px 10px', fontSize: 12, color: tokens.fg[1], lineHeight: 1.5 }}>
              <strong>Body:</strong> {body}<br/><strong>Button:</strong> {button}
            </div>
          </div>
          <div style={{
            background: tokens.bg.surface2, border: `1px solid ${tokens.border.base}`,
            borderRadius:6, overflow: 'hidden',
          }}>
            <div style={{
              height: 140, background: tokens.bg.app,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: tokens.fg[4], fontSize: 11, fontFamily: tokens.font.mono,
            }}>dma_template_image_0{num}.png</div>
            <div style={{ padding: '8px 12px', fontSize: 11, color: tokens.fg[3], fontFamily: tokens.font.mono }}>DMA configured</div>
            <div style={{ padding: '0 12px 10px', fontSize: 12, color: tokens.fg[1], lineHeight: 1.5 }}>
              <strong>Body:</strong> {body}<br/><strong>Button:</strong> {button}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── AI ─────────────────────────────────────────────────────────────────
function AIPanel({ ticket }) {
  return (
    <div>
      <Badge kind="danger">2 issue(s) found</Badge>
      <div style={{
        background: tokens.bg.surface1, border: `1px solid ${tokens.danger.border}`,
        borderRadius:6, padding: '20px 24px', marginTop: 10,
        fontSize: 13, lineHeight: 1.9, color: tokens.fg[1],
      }}>
        <H3>Body comparison</H3>
        <Li><Pass/> Greeting matches JIRA.</Li>
        <Li><Pass/> Date placeholders match: <Code>{'{{leaflet_start_date}}'}</Code>, <Code>{'{{leaflet_end_date}}'}</Code>.</Li>
        <Li><Fail/> Footer line missing — <Em>JIRA: "Hier bin ich richtig" / API: "(empty)"</Em>.</Li>

        <H3>CTA</H3>
        <Li><Fail/> Button text mismatch: <Strong>"Zum Prospekt"</Strong> not in API set <Code>["Mehr erfahren"]</Code>.</Li>

        <H3>Audience filters</H3>
        <Li><Pass/> All required include filters present.</Li>
        <Li><Pass/> No unexpected exclude filters.</Li>

        <H3>Recommendation</H3>
        <Li>Update the DMA template buttons to include <Code>"Zum Prospekt"</Code> before approving this sendout.</Li>
      </div>
    </div>
  );
}

const H3 = ({ children }) => <div style={{ fontSize: 11, fontWeight: 600, color: tokens.brand.text, textTransform: 'uppercase', letterSpacing: '0.05em', margin: '14px 0 4px' }}>{children}</div>;
const Li = ({ children }) => <div style={{ padding: '2px 0 2px 10px', lineHeight: 1.7 }}>{children}</div>;
const Pass = () => <span style={{ color: tokens.ok.base }}>✅</span>;
const Fail = () => <span style={{ color: tokens.danger.base }}>❌</span>;
const Code = ({ children }) => <code style={{ background: tokens.bg.surface3, padding: '1px 5px', borderRadius: 3, fontFamily: tokens.font.mono, fontSize: 11, color: tokens.fg[1] }}>{children}</code>;
const Em = ({ children }) => <em style={{ color: tokens.fg[2], fontStyle: 'italic' }}>{children}</em>;
const Strong = ({ children }) => <strong style={{ color: tokens.fg[1], fontWeight: 600 }}>{children}</strong>;

Object.assign(window, { ValidatorPanel });
