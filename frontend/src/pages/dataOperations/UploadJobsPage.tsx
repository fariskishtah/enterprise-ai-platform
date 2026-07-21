import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import type { PaginatedResponse } from "../../api/hierarchy";
import {
  listUploadJobs,
  type UploadJob,
  type UploadJobStatus,
} from "../../api/sensorData";
import { useAuth } from "../../auth/useAuth";
import { CsvUploadDialog } from "../../components/dataOperations/CsvUploadDialog";
import { UploadJobSummary } from "../../components/dataOperations/UploadJobSummary";
import { PageHeader } from "../../components/ui/PageHeader";
import {
  Breadcrumbs,
  EmptyState,
  InlineError,
  LoadingSkeleton,
  PaginationControls,
  primaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { hierarchyError } from "../hierarchy/shared";

const PAGE_SIZE = 20;

export function UploadJobsPage(): ReactElement {
  const { role } = useAuth();
  const canWrite = role === "admin" || role === "engineer";
  const [page, setPage] = useState<PaginatedResponse<UploadJob> | null>(null);
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState<UploadJobStatus | "">("");
  const [appliedStatus, setAppliedStatus] = useState<UploadJobStatus | undefined>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    listUploadJobs({
      limit: PAGE_SIZE,
      offset,
      signal: controller.signal,
      status: appliedStatus,
    })
      .then((result) => {
        if (active) {
          setPage(result);
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
  }, [appliedStatus, offset, revision]);
  const reload = (): void => {
    setLoading(true);
    setError(null);
    setRevision((value) => value + 1);
  };

  return (
    <section aria-labelledby="uploads-heading">
      <Breadcrumbs
        items={[{ label: "Sensor Data", to: "/sensor-data" }, { label: "Upload jobs" }]}
      />
      <PageHeader
        actions={
          canWrite ? (
            <button
              className={primaryButtonClassName}
              onClick={() => setShowUpload(true)}
              type="button"
            >
              Upload CSV
            </button>
          ) : undefined
        }
        description="Review aggregate results from sensor-data ingestion jobs."
        eyebrow="Data operations"
        headingId="uploads-heading"
        title="Upload jobs"
      />
      <form
        className="mt-6 flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          setLoading(true);
          setError(null);
          setOffset(0);
          setAppliedStatus(status === "" ? undefined : status);
        }}
      >
        <div>
          <label
            className="block text-sm font-medium text-neutral-800"
            htmlFor="upload-status"
          >
            Status
          </label>
          <select
            className="mt-2 rounded-md border border-neutral-300 px-3 py-2 text-sm"
            id="upload-status"
            onChange={(event) => setStatus(event.target.value as UploadJobStatus | "")}
            value={status}
          >
            <option value="">All statuses</option>
            <option value="PENDING">Pending</option>
            <option value="PROCESSING">Processing</option>
            <option value="COMPLETED">Completed</option>
            <option value="FAILED">Failed</option>
          </select>
        </div>
        <button
          className="rounded-md border border-neutral-300 bg-white px-4 py-2 text-sm font-semibold hover:bg-neutral-100"
          type="submit"
        >
          Apply filter
        </button>
      </form>
      <div className="mt-5">
        {loading ? (
          <LoadingSkeleton label="Loading upload jobs" />
        ) : error !== null ? (
          <InlineError message={error} onRetry={reload} />
        ) : page === null || page.total === 0 ? (
          <EmptyState
            action={
              canWrite ? (
                <button
                  className={primaryButtonClassName}
                  onClick={() => setShowUpload(true)}
                  type="button"
                >
                  Upload CSV
                </button>
              ) : undefined
            }
            description="No upload jobs match the current filter."
            title="No upload jobs"
          />
        ) : (
          <>
            <ul className="grid gap-4 lg:grid-cols-2">
              {page.items.map((job) => (
                <li key={job.id}>
                  <UploadJobSummary job={job} />
                </li>
              ))}
            </ul>
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
          </>
        )}
      </div>
      <p className="mt-6 text-sm text-neutral-500">
        Looking for a sensor?{" "}
        <Link className="font-semibold text-purple-700 hover:underline" to="/factories">
          Browse the factory hierarchy
        </Link>
        .
      </p>
      {showUpload ? (
        <CsvUploadDialog onClose={() => setShowUpload(false)} onImported={reload} />
      ) : null}
    </section>
  );
}
