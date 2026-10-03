import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5" aria-label="TrustBreak home">
      <span className="grid size-8 place-items-center rounded-lg bg-brand-700">
        <svg viewBox="0 0 24 24" className="size-5 text-white" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 3 4.5 6v5.5c0 4.4 3.1 7.6 7.5 9.5 4.4-1.9 7.5-5.1 7.5-9.5V6L12 3Z" />
          <path d="m9 12 2.2 2.2L15.5 10" />
        </svg>
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold tracking-tight text-slate-900">TrustBreak</span>
        <span className="block text-[10px] font-medium uppercase tracking-[0.14em] text-slate-500">Fraud defense</span>
      </span>
    </Link>
  );
}

const NAV = [
  { to: "/", label: "Dashboard", isActive: (p) => p === "/" },
  { to: "/incidents", label: "Incidents", isActive: (p) => p.startsWith("/incidents") && p !== "/incidents/new" },
  { to: "/incidents/new", label: "New incident", isActive: (p) => p === "/incidents/new" },
];

function navClass(active) {
  return `flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors ${
    active ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
  }`;
}

export default function Layout() {
  const { pathname } = useLocation();
  return (
    <div className="min-h-screen md:flex">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-200 bg-white md:flex">
        <div className="px-5 py-5">
          <Logo />
        </div>
        <nav className="flex-1 space-y-1 px-3" aria-label="Primary">
          {NAV.map((item) => (
            <NavLink key={item.to} to={item.to} className={navClass(item.isActive(pathname))}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-200 px-5 py-4 text-xs leading-relaxed text-slate-500">
          <p className="font-semibold text-slate-700">Hackathon MVP</p>
          <p>Synthetic data only. Analysis is a placeholder.</p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 md:hidden">
          <Logo />
          <nav className="flex gap-1" aria-label="Primary">
            {NAV.map((item) => (
              <NavLink key={item.to} to={item.to} className={navClass(item.isActive(pathname))}>
                {item.label === "New incident" ? "New" : item.label}
              </NavLink>
            ))}
          </nav>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 md:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
