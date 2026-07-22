import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import {
  listDatasets,
  type DatasetKind,
  type DatasetPage,
  type DatasetStatus,
} from "../../api/datasets";
import { isRequestCancelled } from "../../api/client";
import { LifecycleStatus } from "../../components/dataRag/DataRagUi";
import {
  EmptyState,
  InlineError,
  LoadingSkeleton,
  PaginationControls,
  primaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatDate, hierarchyError } from "../hierarchy/shared";

const PAGE_SIZE = 20;

export function DatasetsPage(): ReactElement {
  const [page, setPage] = useState<DatasetPage | null>(null);
  const [kind, setKind] = useState<DatasetKind | "">("");
  const [status, setStatus] = useState<DatasetStatus | "">("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listDatasets({
      kind: kind || undefined,
      limit: PAGE_SIZE,
      offset,
      signal: controller.signal,
      status: status || undefined,
    })
      .then((result) => {
        if (controller.signal.aborted) return;
        setPage(result);
        setError(null);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (isRequestCancelled(caught, controller.signal)) return;
        setError(hierarchyError(caught));
        setLoading(false);
      });
    return () => controller.abort();
  }, [kind, offset, revision, status]);

  const changeFilter = (): void => {
    setOffset(0);
    setLoading(true);
    setError(null);
  };

  return (
    <section aria-labelledby="datasets-heading">
      <PageHeader
        actions={
          <Link className={primaryButtonClassName} to="/datasets/new">
            Register dataset
          </Link>
        }
        description="Register immutable tabular and document dataset versions for authorized platform workflows."
        eyebrow="Data foundation"
        headingId="datasets-heading"
        title="Dataset Registry"
      />
      <div className="mt-6 grid gap-3 rounded-lg border border-border bg-card p-4 sm:grid-cols-2 lg:max-w-2xl">
        <label className="text-sm font-medium text-foreground">
          Kind
          <select
            className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
            onChange={(event) => {
              changeFilter();
              setKind(event.target.value as DatasetKind | "");
            }}
            value={kind}
          >
            <option value="">All kinds</option>
            <option value="tabular">Tabular</option>
            <option value="document_collection">Document collection</option>
          </select>
        </label>
        <label className="text-sm font-medium text-foreground">
          Status
          <select
            className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
            onChange={(event) => {
              changeFilter();
              setStatus(event.target.value as DatasetStatus | "");
            }}
            value={status}
          >
            <option value="">All statuses</option>
            <option value="active">Active</option>
            <option value="archived">Archived</option>
            <option value="failed">Failed</option>
          </select>
        </label>
      </div>
      <div className="mt-5">
        {loading && page === null ? (
          <LoadingSkeleton label="Loading datasets" />
        ) : error !== null ? (
          <InlineError
            message={error}
            onRetry={() => {
              setLoading(true);
              setRevision((value) => value + 1);
            }}
          />
        ) : page === null || page.items.length === 0 ? (
          <EmptyState
            action={
              <Link className={primaryButtonClassName} to="/datasets/new">
                Register dataset
              </Link>
            }
            description="Upload a small bounded tabular file or document to create the first immutable version."
            title="No datasets"
          />
        ) : (
          <>
            <ul className="grid gap-4 lg:grid-cols-2">
              {page.items.map((dataset) => (
                <li
                  className="rounded-lg border border-border bg-card p-5 shadow-panel"
                  key={dataset.id}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        className="break-words text-lg font-semibold text-link hover:underline"
                        to={`/datasets/${dataset.id}`}
                      >
                        {dataset.name}
                      </Link>
                      <p className="mt-1 text-sm text-secondary-foreground">
                        {dataset.kind.replaceAll("_", " ")}
                      </p>
                    </div>
                    <LifecycleStatus status={dataset.status} />
                  </div>
                  <p className="mt-4 line-clamp-2 text-sm text-muted-foreground">
                    {dataset.description ?? "No description provided."}
                  </p>
                  <p className="mt-4 text-xs text-muted-foreground">
                    Updated {formatDate(dataset.updated_at)}
                  </p>
                </li>
              ))}
            </ul>
            <PaginationControls
              limit={page.limit}
              offset={page.offset}
              onPageChange={(next) => {
                setLoading(true);
                setOffset(next);
              }}
              total={page.total}
            />
          </>
        )}
      </div>
    </section>
  );
}
