import { useEffect, useState, type ReactElement } from "react";
import { useParams } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import { getDatasetDocument, type DatasetDocumentDetail } from "../../api/datasets";
import {
  KeyValueGrid,
  LifecycleCard,
  LifecycleStatus,
} from "../../components/dataRag/DataRagUi";
import {
  Breadcrumbs,
  InlineError,
  LoadingSkeleton,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatDate, hierarchyError } from "../hierarchy/shared";

export function DatasetDocumentPage(): ReactElement {
  const { datasetId = "", versionId = "", documentId = "" } = useParams();
  const [document, setDocument] = useState<DatasetDocumentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getDatasetDocument(datasetId, versionId, documentId, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setDocument(result);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal))
          setError(hierarchyError(caught));
      });
    return () => controller.abort();
  }, [datasetId, documentId, revision, versionId]);

  if (document === null && error === null)
    return <LoadingSkeleton label="Loading document metadata" />;
  if (document === null)
    return (
      <InlineError
        message={error ?? "The requested document is unavailable."}
        onRetry={() => {
          setError(null);
          setRevision((value) => value + 1);
        }}
      />
    );

  return (
    <section aria-labelledby="dataset-document-heading">
      <Breadcrumbs
        items={[
          { label: "Dataset Registry", to: "/datasets" },
          { label: "Dataset", to: `/datasets/${datasetId}` },
          { label: "Version", to: `/datasets/${datasetId}/versions/${versionId}` },
          { label: document.title },
        ]}
      />
      <PageHeader
        description="Bounded extracted metadata preview from a registered document."
        eyebrow="Registered document"
        headingId="dataset-document-heading"
        title={document.title}
      />
      <div className="mt-5">
        <LifecycleStatus status={document.status} />
      </div>
      {document.safe_error_message === null ? null : (
        <p
          className="mt-4 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-800"
          role="alert"
        >
          {document.safe_error_message}
        </p>
      )}
      <div className="mt-6">
        <LifecycleCard>
          <KeyValueGrid
            items={[
              { label: "Filename", value: document.source_filename },
              { label: "Media type", value: document.media_type },
              { label: "Size", value: `${document.size_bytes.toLocaleString()} bytes` },
              { label: "Pages", value: document.page_count ?? "Not available" },
              {
                label: "Extracted characters",
                value: document.extracted_character_count.toLocaleString(),
              },
              { label: "Created", value: formatDate(document.created_at) },
            ]}
          />
        </LifecycleCard>
      </div>
      <section className="mt-7" aria-labelledby="document-preview-heading">
        <h3 className="text-lg font-semibold" id="document-preview-heading">
          Safe text preview
        </h3>
        <div className="mt-4 rounded-lg border border-border bg-card p-5 shadow-panel">
          {document.text_preview === null ? (
            <p className="text-sm text-muted-foreground">
              Extracted text preview is not available.
            </p>
          ) : (
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words font-sans text-sm leading-6 text-foreground">
              {document.text_preview}
            </pre>
          )}
        </div>
      </section>
    </section>
  );
}
