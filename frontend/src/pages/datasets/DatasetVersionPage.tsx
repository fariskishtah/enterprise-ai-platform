import { useEffect, useState, type ReactElement } from "react";
import { Link, useLocation, useParams } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  getDataset,
  getDatasetVersion,
  getDatasetVersionSchema,
  listDatasetDocuments,
  type DatasetDetail,
  type DatasetDocumentPage,
  type DatasetVersionDetail,
} from "../../api/datasets";
import {
  KeyValueGrid,
  LifecycleCard,
  LifecycleStatus,
  SafeMetadata,
  terminalDatasetVersionStatuses,
} from "../../components/dataRag/DataRagUi";
import {
  Breadcrumbs,
  EmptyState,
  InlineError,
  InlineNotice,
  LoadingSkeleton,
  PaginationControls,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatDate, hierarchyError } from "../hierarchy/shared";

const POLL_INTERVAL_MS = 3_000;
const PAGE_SIZE = 20;

export function DatasetVersionPage(): ReactElement {
  const { datasetId = "", versionId = "" } = useParams();
  const location = useLocation();
  const [dataset, setDataset] = useState<DatasetDetail | null>(null);
  const [version, setVersion] = useState<DatasetVersionDetail | null>(null);
  const [schema, setSchema] = useState<Readonly<Record<string, unknown>>>({});
  const [documents, setDocuments] = useState<DatasetDocumentPage | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async (): Promise<void> => {
      try {
        const [nextDataset, nextVersion] = await Promise.all([
          getDataset(datasetId, controller.signal),
          getDatasetVersion(datasetId, versionId, controller.signal),
        ]);
        if (controller.signal.aborted) return;
        setDataset(nextDataset);
        setVersion(nextVersion);
        setSchema(nextVersion.schema_snapshot);
        setError(null);
        setLoading(false);
        if (nextVersion.status === "ready" && nextDataset.kind === "tabular") {
          try {
            const response = await getDatasetVersionSchema(
              datasetId,
              versionId,
              controller.signal,
            );
            setSchema(response.schema_snapshot);
            setSchemaError(null);
          } catch (caught) {
            if (isRequestCancelled(caught, controller.signal)) return;
            setSchemaError(hierarchyError(caught));
          }
        }
        if (nextDataset.kind === "document_collection") {
          try {
            const nextDocuments = await listDatasetDocuments(datasetId, versionId, {
              limit: PAGE_SIZE,
              offset,
              signal: controller.signal,
            });
            setDocuments(nextDocuments);
            setDocumentsError(null);
          } catch (caught) {
            if (isRequestCancelled(caught, controller.signal)) return;
            setDocumentsError(hierarchyError(caught));
          }
        }
        if (!terminalDatasetVersionStatuses.has(nextVersion.status))
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
  }, [datasetId, offset, revision, versionId]);

  if (loading && version === null)
    return <LoadingSkeleton label="Loading dataset version" />;
  if (error !== null || version === null || dataset === null)
    return (
      <InlineError
        message={error ?? "The requested dataset version is unavailable."}
        onRetry={() => setRevision((value) => value + 1)}
      />
    );
  return (
    <section aria-labelledby="dataset-version-heading">
      <Breadcrumbs
        items={[
          { label: "Dataset Registry", to: "/datasets" },
          { label: dataset.name, to: `/datasets/${dataset.id}` },
          { label: `Version ${version.version_number}` },
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
        description="Immutable stored object, processing outcome, schema, and lineage."
        eyebrow={dataset.name}
        headingId="dataset-version-heading"
        title={`Version ${version.version_number}`}
      />
      <div
        className="mt-5 flex flex-wrap items-center gap-3"
        data-testid="dataset-version-status"
      >
        <LifecycleStatus status={version.status} />
        <span className="text-sm text-muted-foreground">
          {version.original_filename ?? "Generated dataset"}
        </span>
      </div>
      {version.safe_error_message === null ? null : (
        <p
          className="mt-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
          role="alert"
        >
          {version.safe_error_message}
        </p>
      )}
      <div className="mt-6">
        <LifecycleCard>
          <KeyValueGrid
            items={[
              { label: "Media type", value: version.media_type },
              { label: "Size", value: `${version.size_bytes.toLocaleString()} bytes` },
              {
                label: dataset.kind === "tabular" ? "Rows" : "Documents",
                value: version.row_count ?? version.document_count ?? "Pending",
              },
              {
                label: dataset.kind === "tabular" ? "Columns" : "Chunks",
                value: version.column_count ?? version.chunk_count ?? "Pending",
              },
              { label: "Created", value: formatDate(version.created_at) },
              {
                label: "Ready",
                value: version.ready_at ? formatDate(version.ready_at) : "Not ready",
              },
              { label: "Source", value: version.source_type.replaceAll("_", " ") },
              { label: "SHA-256", value: version.sha256_digest },
            ]}
          />
        </LifecycleCard>
      </div>
      {dataset.kind === "tabular" ? (
        <section className="mt-7" aria-labelledby="dataset-schema-heading">
          <h3 className="text-lg font-semibold" id="dataset-schema-heading">
            Tabular schema
          </h3>
          <div className="mt-4">
            {schemaError === null ? null : (
              <div className="mb-4">
                <SectionError
                  message={schemaError}
                  onRetry={() => setRevision((value) => value + 1)}
                  title="Unable to refresh the processed schema"
                />
              </div>
            )}
            <LifecycleCard>
              <SafeMetadata
                emptyLabel="Schema will appear when processing completes."
                value={schema}
              />
            </LifecycleCard>
          </div>
        </section>
      ) : (
        <Documents
          datasetId={dataset.id}
          documents={documents}
          error={documentsError}
          onPageChange={setOffset}
          onRetry={() => setRevision((value) => value + 1)}
          versionId={version.id}
        />
      )}
      <section className="mt-7" aria-labelledby="dataset-lineage-heading">
        <h3 className="text-lg font-semibold" id="dataset-lineage-heading">
          Lineage and processing
        </h3>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <LifecycleCard>
            <h4 className="mb-3 font-semibold">Lineage</h4>
            <SafeMetadata value={version.lineage_snapshot} />
          </LifecycleCard>
          <LifecycleCard>
            <h4 className="mb-3 font-semibold">Processing summary</h4>
            <SafeMetadata value={version.processing_summary} />
          </LifecycleCard>
        </div>
      </section>
    </section>
  );
}

function Documents({
  datasetId,
  documents,
  error,
  onPageChange,
  onRetry,
  versionId,
}: {
  readonly datasetId: string;
  readonly documents: DatasetDocumentPage | null;
  readonly error: string | null;
  readonly onPageChange: (value: number) => void;
  readonly onRetry: () => void;
  readonly versionId: string;
}): ReactElement {
  return (
    <section className="mt-7" aria-labelledby="dataset-documents-heading">
      <h3 className="text-lg font-semibold" id="dataset-documents-heading">
        Documents
      </h3>
      <div className="mt-4">
        {error !== null ? (
          <SectionError
            message={error}
            onRetry={onRetry}
            title="Unable to load documents"
          />
        ) : documents === null || documents.items.length === 0 ? (
          <EmptyState
            description="Documents will appear after extraction begins."
            title="No processed documents"
          />
        ) : (
          <>
            <ul className="grid gap-3 lg:grid-cols-2">
              {documents.items.map((document) => (
                <li
                  className="rounded-lg border border-border bg-card p-4"
                  key={document.id}
                >
                  <div className="flex items-start justify-between gap-3">
                    <Link
                      className="break-words font-semibold text-link hover:underline"
                      to={`/datasets/${datasetId}/versions/${versionId}/documents/${document.id}`}
                    >
                      {document.title}
                    </Link>
                    <LifecycleStatus status={document.status} />
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {document.media_type} · {document.size_bytes.toLocaleString()} bytes
                  </p>
                </li>
              ))}
            </ul>
            <PaginationControls
              limit={documents.limit}
              offset={documents.offset}
              onPageChange={onPageChange}
              total={documents.total}
            />
          </>
        )}
      </div>
    </section>
  );
}

function SectionError({
  message,
  onRetry,
  title,
}: {
  readonly message: string;
  readonly onRetry: () => void;
  readonly title: string;
}): ReactElement {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 p-5" role="alert">
      <h4 className="font-semibold text-red-900">{title}</h4>
      <p className="mt-1 text-sm text-red-800">{message}</p>
      <button
        className="mt-3 rounded-md border border-red-300 bg-white px-3 py-2 text-sm font-semibold text-red-800"
        onClick={onRetry}
        type="button"
      >
        Try again
      </button>
    </div>
  );
}
