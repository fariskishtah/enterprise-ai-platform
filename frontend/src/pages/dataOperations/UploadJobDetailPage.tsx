import { useEffect, useState, type ReactElement } from "react";
import { Link, useParams } from "react-router-dom";

import { getUploadJob, type UploadJob } from "../../api/sensorData";
import { UploadJobSummary } from "../../components/dataOperations/UploadJobSummary";
import {
  Breadcrumbs,
  InlineError,
  LoadingSkeleton,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { hierarchyError } from "../hierarchy/shared";

export function UploadJobDetailPage(): ReactElement {
  const { uploadJobId = "" } = useParams();
  const [job, setJob] = useState<UploadJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    getUploadJob(uploadJobId, controller.signal)
      .then((result) => {
        if (active) {
          setJob(result);
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
  }, [revision, uploadJobId]);
  const retry = (): void => {
    setLoading(true);
    setError(null);
    setRevision((value) => value + 1);
  };

  if (loading) return <LoadingSkeleton label="Loading upload job" />;
  if (error !== null || job === null)
    return (
      <InlineError message={error ?? "Upload job is unavailable."} onRetry={retry} />
    );

  return (
    <section aria-labelledby="upload-detail-heading">
      <Breadcrumbs
        items={[
          { label: "Sensor Data", to: "/sensor-data" },
          { label: "Upload jobs", to: "/sensor-data/uploads" },
          { label: job.filename },
        ]}
      />
      <div className="border-b border-neutral-200 pb-6">
        <p className="text-sm font-semibold uppercase tracking-wider text-teal-700">
          Import result
        </p>
        <h2
          className="mt-2 text-3xl font-semibold tracking-tight"
          id="upload-detail-heading"
        >
          {job.filename}
        </h2>
        <p className="mt-2 text-sm text-neutral-600">
          This result reflects the backend’s immediate validation and import operation.
        </p>
      </div>
      <div className="mt-6">
        <UploadJobSummary job={job} />
      </div>
      <p className="mt-5 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">
        Row-level rejection details and sensor data-quality metrics are not available
        from the current backend API.
      </p>
      <div className="mt-6 flex flex-wrap gap-3">
        <Link className={secondaryButtonClassName} to="/sensor-data/uploads">
          Back to upload jobs
        </Link>
        <Link className={secondaryButtonClassName} to="/sensor-data">
          Sensor Data home
        </Link>
      </div>
    </section>
  );
}
