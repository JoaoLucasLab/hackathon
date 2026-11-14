import { LayoutDashboard, Menu, X } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { APP_NAME, TERM_LABEL } from "../../config";

export function NavBar() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const links = [{ to: "/", label: "Plan" }, { to: "/schedules", label: "Schedules" }, { to: "/professors", label: "Professors" }];
  return (
    <header className="sticky top-4 z-20 mx-auto mt-4 w-full max-w-[1168px] px-5 md:px-6">
      <nav aria-label="Main" className="relative flex min-h-[62px] items-center justify-between rounded-nav px-[18px]">
        <Link to="/" className="flex min-h-11 items-center gap-2.5 rounded-btn font-semibold" onClick={() => setOpen(false)}>
          <span aria-hidden="true" className="grid size-7 place-items-center rounded-[7px] bg-ink text-surface"><LayoutDashboard size={17} /></span>
          {APP_NAME}
        </Link>
        <div className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-7 md:flex">
          {links.map(({ to, label }) => <NavLink key={to} to={to} end={to === "/"} aria-current={to === "/" && pathname === "/planner" ? "page" : undefined} className={({ isActive }) => `flex min-h-11 items-center text-sm ${isActive || (to === "/" && pathname === "/planner") ? "font-semibold text-ink" : "text-muted hover:text-ink"}`}>{label}</NavLink>)}
        </div>
        <span className="hidden text-[13px] text-muted md:block">{TERM_LABEL}</span>
        <button type="button" aria-label={open ? "Close navigation" : "Open navigation"} aria-expanded={open} aria-controls="mobile-navigation" onClick={() => setOpen(!open)} className="grid size-11 place-items-center rounded-btn md:hidden">{open ? <X size={20} /> : <Menu size={20} />}</button>
        {open && <div id="mobile-navigation" className="absolute left-0 right-0 top-[70px] flex flex-col rounded-nav border border-line bg-surface p-3 md:hidden">{links.map(({ to, label }) => <NavLink key={to} to={to} end={to === "/"} aria-current={to === "/" && pathname === "/planner" ? "page" : undefined} onClick={() => setOpen(false)} className={({ isActive }) => `rounded-btn px-3 py-3 text-sm ${isActive ? "bg-field font-semibold" : "text-muted"}`}>{label}</NavLink>)}<span className="px-3 py-2 text-[13px] text-muted">{TERM_LABEL}</span></div>}
      </nav>
    </header>
  );
}
