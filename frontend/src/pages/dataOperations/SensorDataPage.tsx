import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { listUploadJobs, type UploadJob } from "../../api/sensorData";
import { useAuth } from "../../auth/useAuth";
import { CsvUploadDialog } from "../../components/dataOperations/CsvUploadDialog";
import { UploadJobSummary } from "../../components/dataOperations/UploadJobSummary";
import {
  EmptyState,
  InlineError,
  LoadingSkeleton,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { hierarchyError } from "../hierarchy/shared";

export function SensorDataPage(): ReactElement {
  const { role } = useAuth();
  const canWrite = role === "admin" || role === "engineer";
  const [jobs, setJobs] = useState<readonly UploadJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    listUploadJobs({ limit: 5, signal: controller.signal })
      .then((page) => {
        if (active) {
          setJobs(page.items);
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
  }, [revision]);

  const retry = (): void => {
    setLoading(true);
    setError(null);
    setRevision((value) => value + 1);
  };

  return (
    <section aria-labelledby="sensor-data-heading">
      <div className="flex flex-col gap-4 border-b border-neutral-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-teal-700">
            Data operations
          </p>
          <h2
            className="mt-2 text-3xl font-semibold tracking-tight"
            id="sensor-data-heading"
          >
            Sensor Data
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-neutral-600">
            Review CSV ingestion activity or select a sensor through the manufacturing
            hierarchy to inspect and add readings.
          </p>
        </div>
        {canWrite ? (
          <button
            className={primaryButtonClassName}
            onClick={() => setShowUpload(true)}
            type="button"
          >
            Upload CSV
          </button>
        ) : null}
      </div>
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <article className="rounded-lg border border-neutral-200 bg-white p-5">
          <h3 className="font-semibold">Browse sensor readings</h3>
          <p className="mt-2 text-sm leading-6 text-neutral-600">
            Open a factory, choose a machine, then select a sensor to view its newest
            readings and supported filters.
          </p>
          <Link
            className={`mt-5 inline-flex ${secondaryButtonClassName}`}
            to="/factories"
          >
            Browse factories
          </Link>
        </article>
        <article className="rounded-lg border border-neutral-200 bg-white p-5">
          <h3 className="font-semibold">CSV imports</h3>
          <p className="mt-2 text-sm leading-6 text-neutral-600">
            CSV files are validated and imported immediately. Import history provides
            aggregate accepted and invalid row counts.
          </p>
          <Link
            className={`mt-5 inline-flex ${secondaryButtonClassName}`}
            to="/sensor-data/uploads"
          >
            View all uploads
          </Link>
        </article>
      </div>
      <div className="mt-8 flex items-center justify-between gap-4">
        <div>
          <h3 className="text-xl font-semibold">Recent upload jobs</h3>
          <p className="mt-1 text-sm text-neutral-600">
            Most recently created CSV and API ingestion jobs.
          </p>
        </div>
        <Link
          className="text-sm font-semibold text-teal-700 hover:underline"
          to="/sensor-data/uploads"
        >
          View all
        </Link>
      </div>
      <div className="mt-4">
        {loading ? (
          <LoadingSkeleton label="Loading recent uploads" />
        ) : error !== null ? (
          <InlineError message={error} onRetry={retry} />
        ) : jobs.length === 0 ? (
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
            description="No upload jobs have been created yet."
            title="No upload history"
          />
        ) : (
          <ul className="grid gap-4 lg:grid-cols-2">
            {jobs.map((job) => (
              <li key={job.id}>
                <UploadJobSummary compact job={job} />
              </li>
            ))}
          </ul>
        )}
      </div>
      {showUpload ? (
        <CsvUploadDialog onClose={() => setShowUpload(false)} onImported={retry} />
      ) : null}
    </section>
  );
}
