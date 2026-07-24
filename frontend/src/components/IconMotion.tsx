import type { ReactElement, ReactNode } from "react";

import type { NavigationMotion } from "../navigation";

export function IconMotion({
  active,
  children,
  motion,
}: {
  readonly active: boolean;
  readonly children: ReactNode;
  readonly motion: NavigationMotion;
}): ReactElement {
  return (
    <span
      aria-hidden="true"
      className={`nav-icon-motion nav-icon-motion--${motion}${active ? " nav-icon-motion--active" : ""}`}
      data-motion={motion}
    >
      {children}
    </span>
  );
}
