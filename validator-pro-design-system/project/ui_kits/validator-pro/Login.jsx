// ui_kits/validator-pro/Login.jsx · v2 tech-futurist
function Login({ onSignIn }) {
  const [u, setU] = React.useState('');
  const [p, setP] = React.useState('');
  const [err, setErr] = React.useState('');
  const [now] = React.useState(() => new Date().toISOString());

  const submit = () => {
    const valid = { gleb: 'Gleb Semeniuk', martina: 'Martina Sesar', alex: 'Alex Volkonitin' };
    if (valid[u.toLowerCase()] && p) onSignIn(valid[u.toLowerCase()]);
    else setErr('Invalid credentials · 4 attempt(s) remaining');
  };

  return (
    <div style={{
      minHeight: '100vh', background: tokens.bg.app,
      display: 'flex', justifyContent: 'center', alignItems: 'center',
      fontFamily: tokens.font.sans, padding: 24,
    }}>
      <HudPanel style={{
        width: 440, padding: 32,
        background: tokens.bg.surface1,
      }}>
        {/* Top label rail */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          fontFamily: tokens.font.mono, fontSize: 10,
          letterSpacing: '0.16em', textTransform: 'uppercase',
          color: tokens.accent.base, marginBottom: 18,
        }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
            <Led kind="accent" pulse /> Secure terminal
          </span>
          <span style={{ color: tokens.fg[4] }}>{now.slice(0, 10)}</span>
        </div>

        {/* Brand mark + product */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 22 }}>
          <img src="../../assets/validator-mark.svg" alt="360dialog" style={{
            width: 52, height: 52, borderRadius: 4, display: 'block',
          }} />
          <div>
            <div style={{
              fontFamily: tokens.font.display, fontWeight: 600, fontSize: 22,
              color: tokens.fg[1], letterSpacing: '-0.01em',
            }}>Validator Pro</div>
            <div style={{
              fontFamily: tokens.font.mono, fontSize: 10,
              letterSpacing: '0.16em', textTransform: 'uppercase',
              color: tokens.fg[3], marginTop: 2,
            }}>360dialog · sendout audit</div>
          </div>
        </div>

        <hr style={{ border: 'none', borderTop: `1px dashed ${tokens.border.hud}`, margin: '0 0 18px' }} />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <div style={{
              fontFamily: tokens.font.mono, fontSize: 10,
              letterSpacing: '0.12em', textTransform: 'uppercase',
              color: tokens.fg[3], marginBottom: 6,
            }}>— Operator</div>
            <Input value={u} onChange={setU} placeholder="gleb / martina / alex" />
          </div>
          <div>
            <div style={{
              fontFamily: tokens.font.mono, fontSize: 10,
              letterSpacing: '0.12em', textTransform: 'uppercase',
              color: tokens.fg[3], marginBottom: 6,
            }}>— Passphrase</div>
            <Input value={p} onChange={setP} type="password" />
          </div>
          {err && (
            <div style={{
              padding: '10px 14px', borderRadius: 4,
              background: tokens.danger.soft2, border: `1px solid ${tokens.danger.ring}`,
              color: tokens.danger.base, fontSize: 12,
              fontFamily: tokens.font.mono, letterSpacing: '0.04em',
              display: 'flex', alignItems: 'center', gap: 8,
            }}><Led kind="danger" pulse /> {err}</div>
          )}
          <Button onClick={submit} style={{ marginTop: 4 }}>Sign in →</Button>
        </div>

        <hr style={{ border: 'none', borderTop: `1px dashed ${tokens.border.hud}`, margin: '22px 0 14px' }} />

        <div style={{
          fontFamily: tokens.font.mono, fontSize: 10, color: tokens.fg[4],
          lineHeight: 1.9, letterSpacing: '0.06em',
        }}>
          <div>LOCKOUT&nbsp;·&nbsp;<span style={{ color: tokens.fg[3] }}>5 attempts / 300s</span></div>
          <div>AUDIT&nbsp;·&nbsp;<span style={{ color: tokens.fg[3] }}>writes to <code style={{ background: tokens.bg.surface3, padding: '1px 5px', borderRadius: 2, color: tokens.fg[2] }}>audit.log</code></span></div>
          <div>BUILD&nbsp;·&nbsp;<span style={{ color: tokens.accent.base }}>2026.05.14-stable</span></div>
        </div>
      </HudPanel>
    </div>
  );
}
Object.assign(window, { Login });
