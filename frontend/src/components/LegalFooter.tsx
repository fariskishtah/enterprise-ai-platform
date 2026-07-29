import type { ReactElement } from "react";
import { Link } from "react-router-dom";

import { legalLinks } from "./legalLinks";

export function LegalFooter(): ReactElement {
  return (
    <footer className="border-t border-neutral-200 bg-white px-5 py-5 text-neutral-600">
      <nav
        aria-label="Legal and policy documents"
        className="mx-auto flex max-w-screen-2xl flex-wrap justify-center gap-x-5 gap-y-2 text-xs"
      >
        {legalLinks.map(([label, to]) => (
          <Link
            className="underline-offset-4 hover:text-purple-800 hover:underline"
            key={to}
            to={to}
          >
            {label}
          </Link>
        ))}
      </nav>
      <p className="mx-auto mt-3 max-w-screen-2xl text-center text-xs">
        Draft placeholders only — qualified legal review is required before production.
      </p>
    </footer>
  );
}
