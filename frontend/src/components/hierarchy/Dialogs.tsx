import { useEffect, useId, useRef, type ReactElement, type ReactNode } from "react";

import { secondaryButtonClassName } from "./ResourceStates";
import { buttonClassName } from "../ui/buttonStyles";

export function Dialog({
  children,
  description,
  onClose,
  title,
}: {
  readonly children: ReactNode;
  readonly description?: string;
  readonly onClose: () => void;
  readonly title: string;
}): ReactElement {
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    const previouslyFocused = document.activeElement;
    const focusable = (): HTMLElement[] =>
      Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
    focusable()[0]?.focus();
    const handleKeyboard = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        onClose();
      } else if (event.key === "Tab") {
        const items = focusable();
        if (items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", handleKeyboard);
    return () => {
      window.removeEventListener("keydown", handleKeyboard);
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    };
  }, [onClose]);

  return (
    <div
      aria-labelledby={titleId}
      aria-modal="true"
      className="fixed inset-0 z-50 overflow-y-auto"
      role="dialog"
    >
      <button
        aria-label="Close dialog"
        className="fixed inset-0 bg-neutral-950/60"
        onClick={onClose}
        type="button"
      />
      <div
        className="relative mx-auto my-6 w-[calc(100%-2rem)] max-w-2xl overflow-hidden rounded-lg border border-neutral-300 bg-white shadow-lg sm:my-12"
        ref={dialogRef}
      >
        <div className="flex items-start justify-between gap-4 border-b border-neutral-200 bg-neutral-50 px-6 py-5 sm:px-7">
          <div>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-purple-700">
              Action required
            </p>
            <h2
              className="text-xl font-semibold tracking-tight text-neutral-950"
              id={titleId}
            >
              {title}
            </h2>
            {description === undefined ? null : (
              <p className="mt-1 text-sm leading-6 text-neutral-600">{description}</p>
            )}
          </div>
          <button
            aria-label="Close dialog"
            className="rounded-md px-2 py-1 text-xl text-neutral-500 hover:bg-neutral-200 hover:text-neutral-900"
            onClick={onClose}
            type="button"
          >
            ×
          </button>
        </div>
        <div className="px-6 py-6 sm:px-7">{children}</div>
      </div>
    </div>
  );
}

export function ConfirmDialog({
  busy,
  error,
  name,
  onCancel,
  onConfirm,
  resourceLabel,
}: {
  readonly busy: boolean;
  readonly error: string | null;
  readonly name: string;
  readonly onCancel: () => void;
  readonly onConfirm: () => void;
  readonly resourceLabel: string;
}): ReactElement {
  return (
    <Dialog
      description={`This will remove ${name} from active use. This action does not hard-delete database history.`}
      onClose={onCancel}
      title={`Remove ${resourceLabel}?`}
    >
      {error === null ? null : (
        <p
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
          role="alert"
        >
          {error}
        </p>
      )}
      <div className="mt-6 flex justify-end gap-3">
        <button
          className={secondaryButtonClassName}
          disabled={busy}
          onClick={onCancel}
          type="button"
        >
          Cancel
        </button>
        <button
          className={buttonClassName("danger")}
          disabled={busy}
          onClick={onConfirm}
          type="button"
        >
          {busy ? "Removing…" : `Remove ${resourceLabel}`}
        </button>
      </div>
    </Dialog>
  );
}
