import { useEffect, useState, type ReactElement } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  archiveDataset,
  createDatasetVersion,
  getDataset,
  listDatasetVersions,
  type DatasetDetail,
  type DatasetVersionPage,
} from "../../api/datasets";
import {
  KeyValueGrid,
  LifecycleCard,
  LifecycleStatus,
  terminalDatasetVersionStatuses,
} from "../../components/dataRag/DataRagUi";
import { Dialog } from "../../components/hierarchy/Dialogs";
import {
  Breadcrumbs,
  EmptyState,
  InlineError,
  InlineNotice,
  LoadingSkeleton,
  PaginationControls,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatDate, hierarchyError } from "../hierarchy/shared";

const PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 4_000;

export function DatasetDetailPage(): ReactElement {
  const { datasetId = "" } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [dataset, setDataset] = useState<DatasetDetail | null>(null);
  const [versions, setVersions] = useState<DatasetVersionPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [targetColumn, setTargetColumn] = useState("");
  const [splitColumn, setSplitColumn] = useState("");
  const [mutating, setMutating] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async (): Promise<void> => {
      try {
        const [nextDataset, nextVersions] = await Promise.all([
          getDataset(datasetId, controller.signal),
          listDatasetVersions(datasetId, {
            limit: PAGE_SIZE,
            offset,
            signal: controller.signal,
          }),
        ]);
        if (controller.signal.aborted) return;
        setDataset(nextDataset);
        setVersions(nextVersions);
        setError(null);
        setLoading(false);
        if (
          nextVersions.items.some(
            (version) => !terminalDatasetVersionStatuses.has(version.status),
          )
        )
          timer = window.setTimeout(() => void load(), POLL_INTERVAL_MS);
      } catch (caught) {
        if (!isRequestCancelled(caught, controller.signal)) {
          setError(hierarchyError(caught));
          setLoading(false);
        }
      }
    };
    void load();
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [datasetId, offset, revision]);

  const archive = async (): Promise<void> => {
    setMutating(true);
    setMutationError(null);
    try {
      await archiveDataset(datasetId);
      setDataset(await getDataset(datasetId));
      setArchiveOpen(false);
    } catch (caught) {
      setMutationError(hierarchyError(caught));
    } finally {
      setMutating(false);
    }
  };

  const uploadVersion = async (): Promise<void> => {
    if (file === null || mutating) return;
    setMutating(true);
    setMutationError(null);
    try {
      const result = await createDatasetVersion(datasetId, file, {
        splitColumn: splitColumn.trim() || undefined,
        targetColumn: targetColumn.trim() || undefined,
      });
      navigate(`/datasets/${datasetId}/versions/${result.id}`, {
        state: { notice: "New immutable dataset version uploaded." },
      });
    } catch (caught) {
      setMutationError(hierarchyError(caught));
      setMutating(false);
    }
  };

  if (loading && dataset === null) return <LoadingSkeleton label="Loading dataset" />;
  if (error !== null && dataset === null)
    return (
      <InlineError message={error} onRetry={() => setRevision((value) => value + 1)} />
    );
  if (dataset === null)
    return (
      <InlineError
        message="The requested dataset is unavailable."
        onRetry={() => setRevision((value) => value + 1)}
      />
    );

  return (
    <section aria-labelledby="dataset-detail-heading">
      <Breadcrumbs
        items={[
          { label: "Dataset Registry", to: "/datasets" },
          { label: dataset.name },
        ]}
      />
      {typeof location.state === "object" &&
      location.state !== null &&
      "notice" in location.state ? (
        <div className="mb-4">
          <InlineNotice>{String(location.state.notice)}</InlineNotice>
        </div>
      ) : null}
      <PageHeader
        actions={
          dataset.status === "active" ? (
            <>
              <button
                className={secondaryButtonClassName}
                onClick={() => {
                  setFile(null);
                  setMutationError(null);
                  setSplitColumn("");
                  setTargetColumn("");
                  setUploadOpen(true);
                }}
                type="button"
              >
                Upload new version
              </button>
              <button
                className={secondaryButtonClassName}
                onClick={() => setArchiveOpen(true)}
                type="button"
              >
                Archive dataset
              </button>
            </>
          ) : undefined
        }
        description={dataset.description ?? "No description provided."}
        eyebrow="Dataset Registry"
        headingId="dataset-detail-heading"
        title={dataset.name}
      />
      <div className="mt-5 flex items-center gap-3">
        <LifecycleStatus status={dataset.status} />
        <span className="text-sm text-muted-foreground">
          {dataset.kind.replaceAll("_", " ")}
        </span>
      </div>
      <div className="mt-6">
        <LifecycleCard>
          <KeyValueGrid
            items={[
              { label: "Versions", value: versions?.total ?? "Loading" },
              { label: "Created", value: formatDate(dataset.created_at) },
              { label: "Updated", value: formatDate(dataset.updated_at) },
              {
                label: "Current version",
                value: dataset.current_version_id ?? "Processing or not available",
              },
            ]}
          />
        </LifecycleCard>
      </div>
      <div className="mt-7">
        <h3 className="text-lg font-semibold text-foreground">Immutable versions</h3>
        <div className="mt-4">
          {versions === null || versions.items.length === 0 ? (
            <EmptyState
              description="This dataset does not have a visible version yet."
              title="No versions"
            />
          ) : (
            <>
              <div
                aria-label="Dataset version history"
                className="overflow-x-auto rounded-lg border border-border bg-card"
                role="region"
                tabIndex={0}
              >
                <table className="min-w-full divide-y divide-border text-left text-sm">
                  <thead className="bg-muted text-xs uppercase">
                    <tr>
                      <th className="px-4 py-3">Version</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3">File</th>
                      <th className="px-4 py-3">Rows / documents</th>
                      <th className="px-4 py-3">Created</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {versions.items.map((version) => (
                      <tr key={version.id}>
                        <td className="px-4 py-3">
                          <Link
                            className="font-semibold text-link hover:underline"
                            to={`/datasets/${dataset.id}/versions/${version.id}`}
                          >
                            Version {version.version_number}
                          </Link>
                        </td>
                        <td className="px-4 py-3">
                          <LifecycleStatus status={version.status} />
                        </td>
                        <td className="max-w-xs break-words px-4 py-3">
                          {version.original_filename ?? "Generated"}
                        </td>
                        <td className="px-4 py-3">
                          {version.row_count ?? version.document_count ?? "—"}
                        </td>
                        <td className="px-4 py-3">{formatDate(version.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <PaginationControls
                limit={versions.limit}
                offset={versions.offset}
                onPageChange={(next) => {
                  setLoading(true);
                  setOffset(next);
                }}
                total={versions.total}
              />
            </>
          )}
        </div>
      </div>
      {archiveOpen ? (
        <Dialog
          description="Archived datasets remain available for lineage and existing references, but cannot accept new versions."
          onClose={() => {
            if (!mutating) setArchiveOpen(false);
          }}
          title="Archive dataset?"
        >
          <MutationError message={mutationError} />
          <div className="mt-6 flex justify-end gap-3">
            <button
              className={secondaryButtonClassName}
              disabled={mutating}
              onClick={() => setArchiveOpen(false)}
              type="button"
            >
              Keep active
            </button>
            <button
              className={primaryButtonClassName}
              disabled={mutating}
              onClick={() => void archive()}
              type="button"
            >
              {mutating ? "Archiving…" : "Archive dataset"}
            </button>
          </div>
        </Dialog>
      ) : null}
      {uploadOpen ? (
        <Dialog
          description="Uploading creates a new immutable version. Existing versions are never overwritten."
          onClose={() => {
            if (!mutating) {
              setFile(null);
              setUploadOpen(false);
            }
          }}
          title="Upload new version"
        >
          <label className="text-sm font-medium text-foreground">
            {dataset.kind === "tabular" ? "CSV file" : "Plain text file"}
            <input
              accept={dataset.kind === "tabular" ? ".csv,text/csv" : ".txt,text/plain"}
              className="mt-2 block w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
              disabled={mutating}
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              type="file"
            />
          </label>
          {dataset.kind === "tabular" ? (
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <label className="text-sm font-medium text-foreground">
                Target column (optional)
                <input
                  className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                  disabled={mutating}
                  maxLength={128}
                  onChange={(event) => setTargetColumn(event.target.value)}
                  value={targetColumn}
                />
              </label>
              <label className="text-sm font-medium text-foreground">
                Split column (optional)
                <input
                  className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                  disabled={mutating}
                  maxLength={128}
                  onChange={(event) => setSplitColumn(event.target.value)}
                  value={splitColumn}
                />
              </label>
            </div>
          ) : null}
          <MutationError message={mutationError} />
          <div className="mt-6 flex justify-end gap-3">
            <button
              className={secondaryButtonClassName}
              disabled={mutating}
              onClick={() => {
                setFile(null);
                setUploadOpen(false);
              }}
              type="button"
            >
              Cancel
            </button>
            <button
              className={primaryButtonClassName}
              disabled={mutating || file === null}
              onClick={() => void uploadVersion()}
              type="button"
            >
              {mutating ? "Uploading…" : "Upload version"}
            </button>
          </div>
        </Dialog>
      ) : null}
    </section>
  );
}

function MutationError({
  message,
}: {
  readonly message: string | null;
}): ReactElement | null {
  return message === null ? null : (
    <p
      className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
      role="alert"
    >
      {message}
    </p>
  );
}
