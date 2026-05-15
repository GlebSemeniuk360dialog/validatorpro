// src/MobileApp.jsx — the Validator Pro mobile shell.
// Wraps Login + main app (Validator queue / Orphans / Dashboard / Profile)
// with three nav patterns: bottom tabs, segmented top, drawer.

const { useState: useStateApp, useEffect: useEffectApp } = React;
const TA = window.tokens;

const TABS = [
  { id: 'Validator', short: 'Validator', glyph: 'V', icon: TabIconValidator },
  { id: 'Orphans',   short: 'Orphans',   glyph: 'O', icon: TabIconOrphan    },
  { id: 'Dashboard', short: 'Stats',     glyph: 'D', icon: TabIconChart     },
  { id: 'Profile',   short: 'Profile',   glyph: 'P', icon: TabIconUser      },
];

// ── Top app bar
function MobileTopBar({ title, subtitle, time }) {
  return (
    <div style={{
      position: 'sticky', top: 0, zIndex: 50,
      background: TA.bg.app,
      borderBottom: `1px solid ${TA.border.base}`,
      padding: '12px 16px 10px',
      display: 'flex', alignItems: 'center', gap: 10,
    }}>
      <img src="assets/validator-mark.svg" alt="" style={{ width: 28, height: 28, borderRadius: 3 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontFamily: TA.font.display, fontWeight: 600, fontSize: 15,
          color: TA.fg[1], letterSpacing: '-0.01em',
        }}>{title}</div>
        <div style={{
          fontFamily: TA.font.mono, fontSize: 9, letterSpacing: '0.16em',
          textTransform: 'uppercase', color: TA.brand.text, marginTop: 1,
        }}>{subtitle}</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <MLed kind="ok" pulse size={6} />
        <span style={{ fontFamily: TA.font.mono, fontSize: 10, color: TA.fg[3], letterSpacing: '0.04em' }}>{time}</span>
      </div>
    </div>
  );
}

// ── Bottom tab bar (default nav)
function BottomTabs({ active, onChange, density }) {
  const h = density === 'compact' ? 56 : 64;
  return (
    <div style={{
      position: 'sticky', bottom: 0, zIndex: 50,
      background: TA.bg.surface1,
      borderTop: `1px solid ${TA.border.base}`,
      paddingBottom: 6,
      display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
      height: h, alignItems: 'stretch',
    }}>
      {TABS.map(t => {
        const a = active === t.id;
        const Icon = t.icon;
        return (
          <button key={t.id} onClick={() => onChange(t.id)} style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', gap: 3, padding: '6px 4px',
            color: a ? TA.brand.text : TA.fg[3],
            position: 'relative',
          }}>
            <Icon active={a} />
            <span style={{
              fontFamily: TA.font.sans, fontSize: 10, fontWeight: 600,
              letterSpacing: '0.04em',
            }}>{t.short}</span>
            {a && (
              <span style={{
                position: 'absolute', top: 0, left: '50%', transform: 'translateX(-50%)',
                width: 22, height: 2, background: TA.brand.base, borderRadius: 1,
                boxShadow: TA.brand.glowSm,
              }} />
            )}
          </button>
        );
      })}
    </div>
  );
}

// ── Segmented top nav (variant)
function SegmentedTopNav({ active, onChange }) {
  return (
    <div style={{
      padding: '8px 14px 6px', background: TA.bg.app,
      borderBottom: `1px solid ${TA.border.base}`,
      position: 'sticky', top: 50, zIndex: 49,
    }}>
      <div style={{
        display: 'flex', gap: 3, background: TA.bg.surface3,
        border: `1px solid ${TA.border.base}`, borderRadius: 6, padding: 3,
      }}>
        {TABS.map(t => {
          const a = active === t.id;
          return (
            <button key={t.id} onClick={() => onChange(t.id)} style={{
              flex: 1, padding: '7px 4px', borderRadius: 4, border: 'none',
              background: a ? TA.brand.base : 'transparent',
              color: a ? '#fff' : TA.fg[2],
              fontFamily: TA.font.sans, fontSize: 11, fontWeight: 600, cursor: 'pointer',
              transition: 'all .18s',
            }}>{t.short}</button>
          );
        })}
      </div>
    </div>
  );
}

// ── Drawer (variant)
function Drawer({ open, active, onChange, onClose, user, onSignOut }) {
  if (!open) return null;
  return (
    <div style={{
      position: 'absolute', inset: 0, zIndex: 100,
      display: 'flex', pointerEvents: open ? 'auto' : 'none',
    }}>
      <div onClick={onClose} style={{
        position: 'absolute', inset: 0, background: 'rgba(15, 24, 40, 0.45)',
      }} />
      <div style={{
        position: 'relative', background: TA.bg.surface1,
        width: '76%', maxWidth: 280, height: '100%',
        borderRight: `1px solid ${TA.border.base}`,
        display: 'flex', flexDirection: 'column', padding: 16, gap: 12,
        animation: 'vp-slide-in .22s ease-out',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <img src="assets/validator-mark.svg" alt="" style={{ width: 36, height: 36, borderRadius: 4 }} />
          <div>
            <div style={{ fontFamily: TA.font.display, fontWeight: 600, fontSize: 15, color: TA.fg[1] }}>Validator Pro</div>
            <div style={{ fontFamily: TA.font.mono, fontSize: 9, letterSpacing: '0.14em', textTransform: 'uppercase', color: TA.fg[3], marginTop: 1 }}>{user}</div>
          </div>
        </div>
        <hr style={{ border: 'none', borderTop: `1px dashed ${TA.border.hud}`, margin: 0 }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {TABS.map(t => {
            const a = active === t.id;
            const Icon = t.icon;
            return (
              <button key={t.id} onClick={() => { onChange(t.id); onClose(); }} style={{
                background: a ? TA.brand.soft : 'transparent',
                border: `1px solid ${a ? TA.brand.ring : 'transparent'}`,
                color: a ? TA.brand.text : TA.fg[1],
                fontFamily: TA.font.sans, fontWeight: 500, fontSize: 14,
                borderRadius: 4, padding: '11px 12px', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 10, textAlign: 'left',
              }}>
                <Icon active={a} /> {t.id}
              </button>
            );
          })}
        </div>
        <div style={{ marginTop: 'auto' }}>
          <MButton variant="danger" fullWidth size="md" onClick={onSignOut}>Sign out</MButton>
        </div>
      </div>
    </div>
  );
}

// ── Tab icons (stroke, 1.5px, matches README's Lucide recommendation)
function TabIconValidator({ active }) {
  const c = active ? TA.brand.base : TA.fg[3];
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 11l3 3L22 4" />
      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
    </svg>
  );
}
function TabIconOrphan({ active }) {
  const c = active ? TA.brand.base : TA.fg[3];
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v4M12 16h.01" />
    </svg>
  );
}
function TabIconChart({ active }) {
  const c = active ? TA.brand.base : TA.fg[3];
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 21h18" />
      <rect x="6" y="13" width="3" height="6" />
      <rect x="11" y="9" width="3" height="10" />
      <rect x="16" y="5" width="3" height="14" />
    </svg>
  );
}
function TabIconUser({ active }) {
  const c = active ? TA.brand.base : TA.fg[3];
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 4-7 8-7s8 3 8 7" />
    </svg>
  );
}

// ── Main App
function MobileApp({ initialUser = null, initialTab = 'Validator', initialLoaded = null }) {
  const [user, setUser]         = useStateApp(initialUser);
  const [tab, setTab]           = useStateApp(initialTab);
  const [loaded, setLoaded]     = useStateApp(initialLoaded);
  const [selected, setSelected] = useStateApp(new Set());
  const [drawerOpen, setDrawer] = useStateApp(false);
  const [now, setNow]           = useStateApp(() => new Date().toISOString().slice(11, 16));
  const tweaks                  = window.useMobileTweaks ? window.useMobileTweaks() : { density: 'comfortable', nav: 'bottom' };

  useEffectApp(() => {
    const t = setInterval(() => setNow(new Date().toISOString().slice(11, 16)), 30000);
    return () => clearInterval(t);
  }, []);

  if (!user) {
    return (
      <div style={{ width: '100%', height: '100%', overflow: 'auto', background: TA.bg.app, fontFamily: TA.font.sans }}>
        <LoginScreen onSignIn={setUser} />
      </div>
    );
  }

  const subtitle = loaded ? `validator · ${loaded.key}` : `360dialog · ops`;
  const contentPad = tweaks.density === 'compact' ? '12px 14px 20px' : '16px 16px 28px';

  // For the segmented-top variant we still show top bar + the segmented control
  // For drawer we show a hamburger in top bar instead of bottom nav
  const showBottomTabs = tweaks.nav === 'bottom' && !loaded;
  const showSegmentedTop = tweaks.nav === 'segmented' && !loaded;
  const showDrawerNav  = tweaks.nav === 'drawer'    && !loaded;

  return (
    <div style={{
      width: '100%', height: '100%', position: 'relative',
      background: TA.bg.app, fontFamily: TA.font.sans, color: TA.fg[1],
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
    }}>
      {/* Top bar */}
      <div style={{
        display: 'flex', alignItems: 'center', position: 'sticky', top: 0, zIndex: 50,
        background: TA.bg.app, borderBottom: `1px solid ${TA.border.base}`,
        padding: '12px 16px 10px',
      }}>
        {showDrawerNav && (
          <button onClick={() => setDrawer(true)} style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            marginRight: 8, padding: 4,
          }}>
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={TA.fg[2]} strokeWidth="1.5" strokeLinecap="round">
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
        )}
        <img src="assets/validator-mark.svg" alt="" style={{ width: 28, height: 28, borderRadius: 3 }} />
        <div style={{ flex: 1, minWidth: 0, marginLeft: 10 }}>
          <div style={{
            fontFamily: TA.font.display, fontWeight: 600, fontSize: 15,
            color: TA.fg[1], letterSpacing: '-0.01em',
          }}>{loaded ? 'Validator' : tab}</div>
          <div style={{
            fontFamily: TA.font.mono, fontSize: 9, letterSpacing: '0.16em',
            textTransform: 'uppercase', color: TA.brand.text, marginTop: 1,
          }}>{subtitle}</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <MLed kind="ok" pulse size={6} />
          <span style={{ fontFamily: TA.font.mono, fontSize: 10, color: TA.fg[3], letterSpacing: '0.04em' }}>{now}</span>
        </div>
      </div>

      {/* Segmented top nav (variant only) */}
      {showSegmentedTop && (
        <SegmentedTopNav active={tab} onChange={(t) => { setTab(t); setLoaded(null); setSelected(new Set()); }} />
      )}

      {/* Content area */}
      <div style={{
        flex: 1, minHeight: 0, overflow: 'auto',
        padding: contentPad, scrollBehavior: 'smooth',
      }}>
        {tab === 'Validator' && !loaded && (
          <QueueScreen
            density={tweaks.density}
            selected={selected}
            setSelected={setSelected}
            onOpen={(r) => setLoaded(r)}
          />
        )}
        {tab === 'Validator' && loaded && (
          <ValidatorScreen ticket={loaded} onBack={() => setLoaded(null)} />
        )}
        {tab === 'Orphans'   && <OrphansScreen />}
        {tab === 'Dashboard' && <DashboardScreen />}
        {tab === 'Profile'   && <ProfileScreen user={user} onSignOut={() => setUser(null)} />}
      </div>

      {/* Bottom tabs (default) */}
      {showBottomTabs && (
        <BottomTabs active={tab} onChange={(t) => { setTab(t); setLoaded(null); setSelected(new Set()); }} density={tweaks.density} />
      )}

      {/* Drawer */}
      {showDrawerNav && (
        <Drawer
          open={drawerOpen} active={tab} user={user}
          onChange={(t) => { setTab(t); setLoaded(null); setSelected(new Set()); }}
          onClose={() => setDrawer(false)}
          onSignOut={() => { setDrawer(false); setUser(null); }}
        />
      )}
    </div>
  );
}

Object.assign(window, { MobileApp });
