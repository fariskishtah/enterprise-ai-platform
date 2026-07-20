import { useEffect, type ReactElement, type ReactNode } from "react";

import { secondaryButtonClassName } from "./ResourceStates";

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
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose]);

  return (
    <div aria-modal="true" className="fixed inset-0 z-50 overflow-y-auto" role="dialog">
      <button
        aria-label="Close dialog"
        className="fixed inset-0 bg-neutral-950/60"
        onClick={onClose}
        type="button"
      />
      <div className="relative mx-auto my-6 w-[calc(100%-2rem)] max-w-2xl rounded-xl border border-neutral-200 bg-white p-6 shadow-xl sm:my-12 sm:p-8">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold text-neutral-950">{title}</h2>
            {description === undefined ? null : (
              <p className="mt-1 text-sm leading-6 text-neutral-600">{description}</p>
            )}
          </div>
          <button
            aria-label="Close dialog"
            className="rounded-md px-2 py-1 text-xl text-neutral-500 hover:bg-neutral-100 hover:text-neutral-900"
            onClick={onClose}
            type="button"
          >
            ×
          </button>
        </div>
        <div className="mt-6">{children}</div>
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
          className="rounded-md bg-red-700 px-4 py-2 text-sm font-semibold text-white hover:bg-red-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-red-700 disabled:cursor-not-allowed disabled:opacity-60"
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
