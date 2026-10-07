import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5" aria-label="TrustBreak home">
      <span className="grid size-8 place-items-center rounded-md bg-brand-800">
        <svg viewBox="0 0 24 24" className="size-5 text-white" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 3 4.5 6v5.5c0 4.4 3.1 7.6 7.5 9.5 4.4-1.9 7.5-5.1 7.5-9.5V6L12 3Z" />
          <path d="m9 12 2.2 2.2L15.5 10" />
        </svg>
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold uppercase tracking-[0.08em] text-slate-900">TrustBreak</span>
        <span className="hidden text-[10px] font-medium uppercase tracking-[0.12em] text-slate-500 sm:block">Trust &amp; Transaction Risk Intelligence</span>
      </span>
    </Link>
  );
}

const NAV = [
  { to: "/", label: "Dashboard", isActive: (p) => p === "/" },
  { to: "/incidents", label: "Incidents", isActive: (p) => p.startsWith("/incidents") },
  { to: "/scenarios", label: "Scenarios", isActive: (p) => p.startsWith("/scenarios") },
  { to: "/identities", label: "Identities", isActive: (p) => p.startsWith("/identities") },
];

function navClass(active) {
  return `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
    active ? "bg-brand-50 text-brand-800" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
  }`;
}

export default function Layout() {
  const { pathname } = useLocation();
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur-sm print:hidden">
        <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-2.5 md:px-8">
          <Logo />
          <nav className="flex items-center gap-1" aria-label="Primary">
            {NAV.map((item) => (
              <NavLink key={item.to} to={item.to} className={navClass(item.isActive(pathname))}>
                {item.label}
              </NavLink>
            ))}
          </nav>
          <Link to="/incidents/new" className="hidden rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-800 hover:bg-slate-50 md:inline-flex">
            New incident
          </Link>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8 md:py-8">
        <Outlet />
      </main>
      <footer className="border-t border-slate-200 bg-white px-4 py-3 text-center text-[11px] text-slate-500 print:hidden">
        Decision support · prototype heuristic risk scores, not fraud probabilities · synthetic data only · nothing is blocked, approved or executed
      </footer>
    </div>
  );
}
