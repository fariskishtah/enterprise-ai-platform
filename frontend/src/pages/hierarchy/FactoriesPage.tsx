import { useEffect, useMemo, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  createFactory,
  listAllCompanies,
  listFactories,
  type Company,
  type Factory,
  type PaginatedResponse,
} from "../../api/hierarchy";
import { useAuth } from "../../auth/useAuth";
import { FactoryFormDialog } from "../../components/hierarchy/HierarchyForms";
import { PageHeader } from "../../components/ui/PageHeader";
import {
  EmptyState,
  InlineError,
  LoadingSkeleton,
  PaginationControls,
  primaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { hierarchyError } from "./shared";

const PAGE_SIZE = 20;

export function FactoriesPage(): ReactElement {
  const { role } = useAuth();
  const canWrite = role === "admin" || role === "engineer";
  const [page, setPage] = useState<PaginatedResponse<Factory> | null>(null);
  const [companies, setCompanies] = useState<readonly Company[]>([]);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      listFactories({ limit: PAGE_SIZE, offset, signal: controller.signal }),
      listAllCompanies(controller.signal),
    ])
      .then(([factoryPage, companyItems]) => {
        if (active) {
          setPage(factoryPage);
          setCompanies(companyItems);
          setLoading(false);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(hierarchyError(caught));
          setLoading(false);
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [offset, revision]);

  const companyNames = useMemo(
    () => new Map(companies.map((company) => [company.id, company.name])),
    [companies],
  );
  const filteredFactories = (page?.items ?? []).filter((factory) => {
    const term = query.trim().toLowerCase();
    return (
      term === "" ||
      factory.name.toLowerCase().includes(term) ||
      factory.location?.toLowerCase().includes(term) === true ||
      companyNames.get(factory.company_id)?.toLowerCase().includes(term) === true
    );
  });

  const reload = (): void => {
    setLoading(true);
    setError(null);
    setRevision((value) => value + 1);
  };

  return (
    <section aria-labelledby="factories-heading">
      <PageHeader
        actions={
          canWrite && companies.length > 0 ? (
            <button
              className={primaryButtonClassName}
              onClick={() => setShowCreate(true)}
              type="button"
            >
              Create factory
            </button>
          ) : undefined
        }
        description="Browse active manufacturing sites and open their machines and sensors."
        eyebrow="Manufacturing hierarchy"
        headingId="factories-heading"
        title="Factories"
      />

      {message === null ? null : (
        <p
          className="mt-5 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
          role="status"
        >
          {message}
        </p>
      )}

      <div className="mt-6">
        {loading ? (
          <LoadingSkeleton label="Loading factories" />
        ) : error !== null ? (
          <InlineError message={error} onRetry={reload} />
        ) : page !== null && page.total === 0 ? (
          <EmptyState
            action={
              canWrite && companies.length > 0 ? (
                <button
                  className={primaryButtonClassName}
                  onClick={() => setShowCreate(true)}
                  type="button"
                >
                  Create factory
                </button>
              ) : undefined
            }
            description={
              companies.length === 0 && canWrite
                ? "A company must exist before a factory can be created."
                : "No active factories are available for this account."
            }
            title="No factories yet"
          />
        ) : (
          <>
            <div className="mb-4 max-w-md">
              <label
                className="block text-sm font-medium text-secondary-foreground"
                htmlFor="factory-filter"
              >
                Filter this page
              </label>
              <input
                className="mt-2 block w-full rounded-md border border-border-strong px-3 py-2 text-sm text-foreground outline-none focus:border-purple-700 focus:ring-2 focus:ring-purple-700/20"
                id="factory-filter"
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Name, location, or company"
                type="search"
                value={query}
              />
            </div>
            {filteredFactories.length === 0 ? (
              <EmptyState
                description="No factories on this page match the current filter."
                title="No matches"
              />
            ) : (
              <ul className="grid gap-4 lg:grid-cols-2">
                {filteredFactories.map((factory) => (
                  <li
                    className="group relative overflow-hidden rounded-lg border border-border bg-card p-5 shadow-panel transition hover:border-border-strong hover:shadow-sm"
                    key={factory.id}
                  >
                    <span
                      aria-hidden="true"
                      className="absolute inset-y-0 left-0 w-1 bg-purple-500 opacity-70"
                    />
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          {companyNames.get(factory.company_id) ??
                            "Company unavailable"}
                        </p>
                        <h3 className="mt-1 truncate text-lg font-semibold text-foreground">
                          {factory.name}
                        </h3>
                        <p className="mt-2 text-sm text-secondary-foreground">
                          {factory.location ?? "Location not provided"}
                        </p>
                      </div>
                      <Link
                        className="shrink-0 text-sm font-semibold text-purple-700 hover:underline"
                        to={`/factories/${factory.id}`}
                      >
                        Open
                      </Link>
                    </div>
                    {factory.description === null ? null : (
                      <p className="mt-4 line-clamp-2 text-sm leading-6 text-secondary-foreground">
                        {factory.description}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {page === null ? null : (
              <PaginationControls
                limit={page.limit}
                offset={page.offset}
                onPageChange={(nextOffset) => {
                  setLoading(true);
                  setError(null);
                  setOffset(nextOffset);
                }}
                total={page.total}
              />
            )}
          </>
        )}
      </div>

      {showCreate ? (
        <FactoryFormDialog
          companies={companies}
          onClose={() => setShowCreate(false)}
          onSave={async (payload) => {
            await createFactory(payload);
            setShowCreate(false);
            setMessage("Factory created successfully.");
            setOffset(0);
            reload();
          }}
        />
      ) : null}
    </section>
  );
}
