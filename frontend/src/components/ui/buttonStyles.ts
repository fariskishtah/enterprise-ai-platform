const buttonBaseClassName =
  "inline-flex min-h-10 items-center justify-center rounded-md px-4 py-2 text-sm font-semibold shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-purple-500 disabled:cursor-not-allowed";

export function buttonClassName(variant: "danger" | "primary" | "secondary"): string {
  const variants = {
    danger: "bg-red-700 text-white hover:bg-red-800 active:bg-red-900",
    primary: "bg-purple-700 text-white hover:bg-purple-800 active:bg-purple-900",
    secondary:
      "border border-neutral-300 bg-white text-neutral-800 hover:border-neutral-400 hover:bg-neutral-50 active:bg-neutral-100",
  } as const;
  return `${buttonBaseClassName} ${variants[variant]}`;
}
