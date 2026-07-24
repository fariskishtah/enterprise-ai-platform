import { useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  listFactories,
  listMachines,
  type Factory,
  type Machine,
} from "../../api/hierarchy";
import { EmptyState, LoadingSkeleton } from "../../components/hierarchy/ResourceStates";
import { OperationalError } from "../../components/operations/OperationalUi";
import { PageHeader } from "../../components/ui/PageHeader";

interface VisibleMachine {
  readonly factory: Factory;
  readonly machine: Machine;
}

export function MachinesPage(): ReactElement {
  const [items, setItems] = useState<readonly VisibleMachine[] | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    listFactories({ limit: 100, signal: controller.signal })
      .then(async (factories) => {
        const pages = await Promise.all(
          factories.items.map(async (factory) => ({
            factory,
            page: await listMachines(factory.id, {
              limit: 100,
              signal: controller.signal,
            }),
          })),
        );
        if (active) {
          setItems(
            pages.flatMap(({ factory, page }) =>
              page.items.map((machine) => ({ factory, machine })),
            ),
          );
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (active && !isRequestCancelled(caught, controller.signal)) setError(caught);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [revision]);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (items ?? []).filter(
      ({ factory, machine }) =>
        normalized === "" ||
        machine.name.toLowerCase().includes(normalized) ||
        factory.name.toLowerCase().includes(normalized) ||
        machine.serial_number?.toLowerCase().includes(normalized),
    );
  }, [items, query]);

  return (
    <section aria-labelledby="machines-heading">
      <PageHeader
        description="Browse machines in your authorized factories and open the operational detail."
        eyebrow="Factory operations"
        headingId="machines-heading"
        title="Machines"
      />
      <label className="mt-6 block max-w-md text-sm font-semibold text-foreground">
        Search visible machines
        <input
          className="mt-2 min-h-11 w-full rounded-md border border-border-strong bg-input px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Machine, factory, or serial number"
          type="search"
          value={query}
        />
      </label>
      <div className="mt-6">
        {error ? (
          <OperationalError
            error={error}
            onRetry={() => {
              setError(null);
              setRevision((value) => value + 1);
            }}
          />
        ) : items === null ? (
          <LoadingSkeleton label="Loading machines" />
        ) : filtered.length === 0 ? (
          <EmptyState
            description={
              items.length === 0
                ? "No machines have been added yet. Ask an administrator to add one."
                : "No visible machine matches this search."
            }
            title={
              items.length === 0 ? "No machines available" : "No matching machines"
            }
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map(({ factory, machine }) => (
              <Link
                className="rounded-lg border border-border border-l-4 border-l-purple-600 bg-card p-5 shadow-panel transition hover:border-purple-400 hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                key={machine.id}
                to={`/factories/${factory.id}/machines/${machine.id}`}
              >
                <p className="text-xs font-semibold uppercase tracking-wide text-eyebrow">
                  {factory.name}
                </p>
                <h2 className="mt-2 text-lg font-semibold text-foreground">
                  {machine.name}
                </h2>
                <p className="mt-2 text-sm text-secondary-foreground">
                  {machine.serial_number ?? "Serial number not recorded"}
                </p>
                <p className="mt-4 text-sm font-semibold text-link">Open machine</p>
              </Link>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
