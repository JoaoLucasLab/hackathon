import { Link } from "react-router-dom";

import { APP_NAME, TERM_LABEL } from "../../config";

export function NavBar() {
  return (
    <header className="sticky top-4 z-10 mx-auto w-full max-w-content px-5 md:px-6">
      <nav
        aria-label="Main"
        className="flex min-h-14 items-center justify-between rounded-nav border border-line bg-surface px-4"
      >
        <Link to="/" className="flex min-h-11 items-center gap-2.5 rounded-btn font-semibold">
          <span
            aria-hidden="true"
            className="grid size-7 place-items-center rounded-[7px] bg-ink font-serif text-[17px] text-surface"
          >
            {APP_NAME.charAt(0)}
          </span>
          {APP_NAME}
        </Link>
        <span className="text-sm text-muted">{TERM_LABEL}</span>
      </nav>
    </header>
  );
}
