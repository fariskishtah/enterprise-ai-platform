import type { ReactElement } from "react";

import type { NavigationIcon } from "../navigation";

type UtilityIcon = "chevron-left" | "close" | "menu";

interface IconProps {
  readonly className?: string;
  readonly name: NavigationIcon | UtilityIcon;
}

const paths: Record<NavigationIcon | UtilityIcon, ReactElement> = {
  audit: (
    <path d="M9 12.75 11.25 15 15 10.5m6-3.75V18a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 18V6a2.25 2.25 0 0 1 2.25-2.25h8.25L21 6.75Z" />
  ),
  "chevron-left": <path d="m15 18-6-6 6-6" />,
  close: <path d="M6 18 18 6M6 6l12 12" />,
  dashboard: (
    <path d="M3.75 3.75h6.5v6.5h-6.5v-6.5Zm10 0h6.5v4.5h-6.5v-4.5Zm0 8h6.5v8.5h-6.5v-8.5Zm-10 2h6.5v6.5h-6.5v-6.5Z" />
  ),
  factories: (
    <path d="M3 20.25h18M4.5 20.25V9l5.25 3V9l5.25 3V4.5h4.5v15.75M7.5 16.5h.75m3 0H12m3 0h.75" />
  ),
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  models: (
    <path d="m12 3 8.25 4.5L12 12 3.75 7.5 12 3Zm-8.25 9L12 16.5l8.25-4.5M3.75 16.5 12 21l8.25-4.5" />
  ),
  monitoring: <path d="M3 12h3l2.25-6 4.5 12 2.5-7H21M4.5 20.25h15" />,
  predictions: <path d="M5.25 19.5 18.75 6m-9 0h9v9M5.25 6v13.5H18.75" />,
  retraining: (
    <path d="M20.25 8.25V3.75h-4.5M3.75 15.75v4.5h4.5M19.1 6.1A8.25 8.25 0 0 0 5.2 8.25m-.3 9.65a8.25 8.25 0 0 0 13.9-2.15" />
  ),
  "sensor-data": (
    <path d="M12 18.75a6.75 6.75 0 1 0 0-13.5m0 13.5a2.25 2.25 0 1 0 0-4.5m0 4.5v2.25m0-15.75V3m-6.75 9H3m18 0h-2.25" />
  ),
  settings: (
    <path d="M9.75 3.75h4.5l.6 2.1 2.06 1.2 2.12-.55 2.25 3.9-1.52 1.55v2.4l1.52 1.55-2.25 3.9-2.12-.55-2.06 1.2-.6 2.1h-4.5l-.6-2.1-2.06-1.2-2.12.55-2.25-3.9 1.52-1.55v-2.4L2.72 10.4l2.25-3.9 2.12.55 2.06-1.2.6-2.1ZM12 15.25a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5Z" />
  ),
  "training-jobs": (
    <path d="M12 6.75V12l3.75 2.25M21 12a9 9 0 1 1-2.64-6.36M18 3.75v4.5h-4.5" />
  ),
  users: (
    <path d="M15.75 7.5a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.5 20.25a7.5 7.5 0 0 1 15 0M18 6.75a3 3 0 0 1 0 5.5M21 20.25a5.25 5.25 0 0 0-3.75-5.03" />
  ),
};

export function Icon({ className = "h-5 w-5", name }: IconProps): ReactElement {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.75"
      viewBox="0 0 24 24"
    >
      {paths[name]}
    </svg>
  );
}
