import type { ReactElement } from "react";
import { Link } from "react-router-dom";

import { legalLinks } from "./legalLinks";

export function LegalFooter(): ReactElement {
  return (
    <footer className="border-t border-neutral-200 bg-[var(--surface)] px-5 py-5 text-neutral-600">
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
      <div className="mx-auto mt-2 text-center text-xs text-neutral-500">
        <span>Business & Technical Inquiries: </span>
        <a className="font-medium text-purple-800 underline hover:text-purple-900" href="mailto:fkishtah@gmail.com">
          fkishtah@gmail.com
        </a>
        <span className="mx-2">•</span>
        <a className="font-medium text-purple-800 underline hover:text-purple-900" href="tel:+201115055205">
          01115055205
        </a>
        <span className="mx-2">•</span>
        <a className="font-medium text-purple-800 underline hover:text-purple-900" href="https://www.linkedin.com/in/faris-kishtah-59370b367" rel="noreferrer" target="_blank">
          LinkedIn
        </a>
      </div>
      <p className="mx-auto mt-2 max-w-screen-2xl text-center text-xs">
        Draft placeholders only — qualified legal review is required before production.
      </p>
    </footer>
  );
}
