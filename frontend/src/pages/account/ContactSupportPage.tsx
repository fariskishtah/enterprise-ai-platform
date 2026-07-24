import { useEffect, useMemo, useState, type FormEvent, type ReactElement } from "react";
import { useLocation } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  listFactories,
  listMachines,
  type Factory,
  type Machine,
} from "../../api/hierarchy";
import {
  createSupportRequest,
  type SupportCategory,
  type SupportRequestResult,
} from "../../api/support";
import { useAuth } from "../../auth/useAuth";
import {
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import {
  inputClassName,
  panelClassName,
} from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";

const categories: readonly { label: string; value: SupportCategory }[] = [
  { label: "Technical problem", value: "technical_problem" },
  { label: "Data import", value: "data_import" },
  { label: "Training", value: "training" },
  { label: "Predictions", value: "predictions" },
  { label: "Alerts and operations", value: "alerts_and_operations" },
  { label: "Reports", value: "reports" },
  { label: "Account access", value: "account_access" },
  { label: "Other", value: "other" },
];

function newIdempotencyKey(): string {
  return `support:${crypto.randomUUID()}`;
}

export function ContactSupportPage(): ReactElement {
  const location = useLocation();
  const { user } = useAuth();
  const originatingPage =
    typeof (location.state as { readonly from?: unknown } | null)?.from === "string"
      ? String((location.state as { readonly from: string }).from)
      : "/support";
  const [factories, setFactories] = useState<readonly Factory[]>([]);
  const [machines, setMachines] = useState<readonly Machine[]>([]);
  const [factoryId, setFactoryId] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [result, setResult] = useState<SupportRequestResult | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState(newIdempotencyKey);

  useEffect(() => {
    const controller = new AbortController();
    void listFactories({ limit: 100, signal: controller.signal })
      .then((value) => {
        setFactories(value.items);
        setLoadError(null);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) {
          setLoadError(
            caught instanceof Error ? caught.message : "Factories unavailable.",
          );
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!factoryId) {
      return;
    }
    const controller = new AbortController();
    void listMachines(factoryId, { limit: 100, signal: controller.signal })
      .then((value) => setMachines(value.items))
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) setMachines([]);
      });
    return () => controller.abort();
  }, [factoryId]);

  const identity = useMemo(
    () =>
      `${user?.email ?? "Authenticated user"} · ${user?.role ?? "role unavailable"}`,
    [user],
  );

  const submit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy(true);
    setSubmitError(null);
    setResult(null);
    void createSupportRequest({
      category: String(values.get("category")) as SupportCategory,
      current_page: originatingPage,
      factory_id: factoryId || undefined,
      idempotency_key: idempotencyKey,
      machine_id: String(values.get("machineId") || "") || undefined,
      message: String(values.get("message")),
      subject: String(values.get("subject")),
    })
      .then((value) => {
        setResult(value);
        if (value.status === "delivered") {
          form.reset();
          setFactoryId("");
          setIdempotencyKey(newIdempotencyKey());
        }
      })
      .catch((caught: unknown) =>
        setSubmitError(
          caught instanceof Error
            ? caught.message
            : "The support request could not be saved.",
        ),
      )
      .finally(() => setBusy(false));
  };

  return (
    <section aria-labelledby="support-heading">
      <PageHeader
        description="Send a bounded support request with your authenticated workspace context. Never include passwords, access tokens, or confidential model payloads."
        eyebrow="Account"
        headingId="support-heading"
        title="Contact Support"
      />
      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(18rem,1fr)]">
        <form className={panelClassName} onSubmit={submit}>
          <label className="block text-sm font-medium text-foreground">
            Subject
            <input
              className={inputClassName}
              maxLength={160}
              minLength={3}
              name="subject"
              required
            />
          </label>
          <label className="mt-4 block text-sm font-medium text-foreground">
            Category
            <select className={inputClassName} name="category" required>
              {categories.map((category) => (
                <option key={category.value} value={category.value}>
                  {category.label}
                </option>
              ))}
            </select>
          </label>
          <label className="mt-4 block text-sm font-medium text-foreground">
            Message
            <textarea
              className={`${inputClassName} min-h-40 resize-y`}
              maxLength={5000}
              minLength={10}
              name="message"
              required
            />
          </label>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="block text-sm font-medium text-foreground">
              Related factory (optional)
              <select
                className={inputClassName}
                onChange={(event) => {
                  setFactoryId(event.target.value);
                  setMachines([]);
                }}
                value={factoryId}
              >
                <option value="">None</option>
                {factories.map((factory) => (
                  <option key={factory.id} value={factory.id}>
                    {factory.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm font-medium text-foreground">
              Related machine (optional)
              <select className={inputClassName} disabled={!factoryId} name="machineId">
                <option value="">None</option>
                {machines.map((machine) => (
                  <option key={machine.id} value={machine.id}>
                    {machine.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {loadError ? (
            <p className="mt-4 text-sm text-warning-800" role="status">
              Optional factory context is unavailable. You can still submit support.
            </p>
          ) : null}
          {submitError ? (
            <p className="mt-4 text-sm text-danger-800" role="alert">
              {submitError}
            </p>
          ) : null}
          {result ? (
            <div
              className={`mt-4 rounded-md border p-4 text-sm ${
                result.status === "delivered"
                  ? "border-success-200 bg-success-50 text-success-800"
                  : "border-warning-200 bg-warning-50 text-warning-900"
              }`}
              role="status"
            >
              <p className="font-semibold">{result.delivery_message}</p>
              <p className="mt-1 break-all">Request ID: {result.id}</p>
            </div>
          ) : null}
          <div className="mt-5 flex flex-wrap gap-3">
            <button className={primaryButtonClassName} disabled={busy} type="submit">
              {busy ? "Submitting…" : "Submit support request"}
            </button>
            <button
              className={secondaryButtonClassName}
              onClick={() => {
                setSubmitError(null);
                setResult(null);
              }}
              type="button"
            >
              Clear status
            </button>
          </div>
        </form>
        <aside className={panelClassName}>
          <h3 className="text-base font-semibold text-foreground">
            Included automatically
          </h3>
          <dl className="mt-4 space-y-3 text-sm">
            <div>
              <dt className="text-muted-foreground">Authenticated account</dt>
              <dd className="break-all font-medium text-foreground">{identity}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Current page</dt>
              <dd className="break-all font-medium text-foreground">
                {originatingPage}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Security</dt>
              <dd className="text-foreground">
                Cookies, passwords, tokens, raw logs, and attachments are never
                included.
              </dd>
            </div>
          </dl>
        </aside>
      </div>
    </section>
  );
}
