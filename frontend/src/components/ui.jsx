import { Link } from "react-router-dom";

/** Shared building blocks so pages stay visually consistent. */

export function PageHeader({ eyebrow, title, subtitle, actions }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">{eyebrow}</p>}
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-slate-600">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ title, aside, children, className = "", padded = true }) {
  return (
    <section className={`rounded-lg border border-slate-200 bg-white shadow-[0_1px_0_rgba(15,23,42,0.03)] ${className}`}>
      {(title || aside) && (
        <div className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">{title}</h2>
          {aside}
        </div>
      )}
      <div className={padded ? "p-5" : ""}>{children}</div>
    </section>
  );
}

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60";
const BUTTON_VARIANTS = {
  primary: "bg-brand-700 text-white hover:bg-brand-800",
  secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50",
};

export function Button({ variant = "primary", className = "", ...props }) {
  return <button className={`${BUTTON_BASE} ${BUTTON_VARIANTS[variant]} ${className}`} {...props} />;
}

export function ButtonLink({ variant = "primary", className = "", ...props }) {
  return <Link className={`${BUTTON_BASE} ${BUTTON_VARIANTS[variant]} ${className}`} {...props} />;
}

/** Label / value pair used in definition lists. */
export function DataRow({ label, children }) {
  return (
    <div className="grid grid-cols-[8.5rem_1fr] gap-3 py-2.5 text-sm">
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 break-words font-medium text-slate-900">{children}</dd>
    </div>
  );
}
