import { useEffect, useState, type FormEvent, type ReactElement } from "react";
import { Link, useNavigate } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import { listAllDatasetVersions, listDatasets } from "../../api/datasets";
import { attachDatasetVersion, createKnowledgeBase } from "../../api/rag";
import { LifecycleCard } from "../../components/dataRag/DataRagUi";
import {
  Breadcrumbs,
  InlineNotice,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";
import { hierarchyError } from "../hierarchy/shared";

interface ReadyVersion {
  readonly datasetId: string;
  readonly datasetName: string;
  readonly versionId: string;
  readonly versionNumber: number;
}

const DATASET_PAGE_SIZE = 20;

export function KnowledgeBaseCreatePage(): ReactElement {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [chunkSize, setChunkSize] = useState(800);
  const [chunkOverlap, setChunkOverlap] = useState(100);
  const [available, setAvailable] = useState<readonly ReadyVersion[]>([]);
  const [selected, setSelected] = useState<readonly string[]>([]);
  const [datasetOffset, setDatasetOffset] = useState(0);
  const [datasetTotal, setDatasetTotal] = useState(0);
  const [datasetRevision, setDatasetRevision] = useState(0);
  const [loadingVersions, setLoadingVersions] = useState(true);
  const [discoveryError, setDiscoveryError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const load = async (): Promise<void> => {
      try {
        const datasets = await listDatasets({
          kind: "document_collection",
          limit: DATASET_PAGE_SIZE,
          offset: datasetOffset,
          signal: controller.signal,
          status: "active",
        });
        const versionPages = await Promise.all(
          datasets.items.map(async (dataset) => ({
            dataset,
            versions: await listAllDatasetVersions(dataset.id, {
              signal: controller.signal,
            }),
          })),
        );
        if (controller.signal.aborted) return;
        setDatasetTotal(datasets.total);
        setAvailable(
          versionPages.flatMap(({ dataset, versions }) =>
            versions
              .filter((version) => version.status === "ready")
              .map((version) => ({
                datasetId: dataset.id,
                datasetName: dataset.name,
                versionId: version.id,
                versionNumber: version.version_number,
              })),
          ),
        );
        setDiscoveryError(null);
        setLoadingVersions(false);
      } catch (caught) {
        if (!isRequestCancelled(caught, controller.signal)) {
          setDiscoveryError(hierarchyError(caught));
          setLoadingVersions(false);
        }
      }
    };
    void load();
    return () => controller.abort();
  }, [datasetOffset, datasetRevision]);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    if (selected.length === 0) {
      setError("Select at least one ready document dataset version.");
      return;
    }
    if (chunkOverlap >= chunkSize) {
      setError("Chunk overlap must be smaller than chunk size.");
      return;
    }
    setSubmitting(true);
    try {
      const knowledgeBase = await createKnowledgeBase({
        chunk_overlap: chunkOverlap,
        chunk_size: chunkSize,
        description: description.trim() || null,
        name: name.trim(),
      });
      let attachedCount = 0;
      try {
        for (const versionId of selected) {
          await attachDatasetVersion(knowledgeBase.knowledge_base_id, versionId);
          attachedCount += 1;
        }
      } catch (caught) {
        navigate(`/knowledge/${knowledgeBase.knowledge_base_id}`, {
          state: {
            notice: `The knowledge base was created and ${attachedCount} of ${selected.length} selected versions were attached. Attach the remaining versions from this page. ${hierarchyError(caught)}`,
          },
        });
        return;
      }
      navigate(`/knowledge/${knowledgeBase.knowledge_base_id}`, {
        state: { notice: "Knowledge base created with registered document versions." },
      });
    } catch (caught) {
      setError(hierarchyError(caught));
      setSubmitting(false);
    }
  };

  return (
    <section aria-labelledby="knowledge-create-heading">
      <Breadcrumbs
        items={[{ label: "Knowledge Bases", to: "/knowledge" }, { label: "Create" }]}
      />
      <PageHeader
        description="Attach only ready, authorized document dataset versions. Embedding provider selection is controlled by the server."
        eyebrow="Grounded AI"
        headingId="knowledge-create-heading"
        title="Create knowledge base"
      />
      <form className="mt-6 max-w-3xl" onSubmit={(event) => void submit(event)}>
        <LifecycleCard>
          <InlineNotice>
            Registered documents are untrusted evidence, never instructions. Indexing
            does not browse the internet or invoke tools.
          </InlineNotice>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <label className="text-sm font-medium sm:col-span-2">
              Name
              <input
                className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                disabled={submitting}
                maxLength={128}
                minLength={3}
                onChange={(event) => setName(event.target.value)}
                required
                value={name}
              />
            </label>
            <label className="text-sm font-medium sm:col-span-2">
              Description (optional)
              <textarea
                className="mt-1 min-h-24 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                disabled={submitting}
                maxLength={2000}
                onChange={(event) => setDescription(event.target.value)}
                value={description}
              />
            </label>
            <label className="text-sm font-medium">
              Chunk size
              <input
                className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                disabled={submitting}
                max={4000}
                min={200}
                onChange={(event) => setChunkSize(Number(event.target.value))}
                type="number"
                value={chunkSize}
              />
            </label>
            <label className="text-sm font-medium">
              Chunk overlap
              <input
                className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                disabled={submitting}
                max={1000}
                min={0}
                onChange={(event) => setChunkOverlap(Number(event.target.value))}
                type="number"
                value={chunkOverlap}
              />
            </label>
          </div>
          <fieldset className="mt-6">
            <legend className="font-semibold">Ready document versions</legend>
            {loadingVersions ? (
              <p
                aria-live="polite"
                className="mt-3 text-sm text-muted-foreground"
                role="status"
              >
                Loading authorized document versions…
              </p>
            ) : discoveryError !== null ? null : available.length === 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">
                No ready document versions are available. Register and process a
                document dataset first.
              </p>
            ) : (
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {available.map((version) => (
                  <label
                    className="flex gap-3 rounded-md border border-border bg-elevated p-3 text-sm"
                    key={version.versionId}
                  >
                    <input
                      checked={selected.includes(version.versionId)}
                      disabled={submitting}
                      onChange={(event) =>
                        setSelected((current) =>
                          event.target.checked
                            ? [...current, version.versionId]
                            : current.filter((id) => id !== version.versionId),
                        )
                      }
                      type="checkbox"
                    />
                    <span>
                      <strong>{version.datasetName}</strong>
                      <span className="block text-xs text-muted-foreground">
                        Version {version.versionNumber}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            )}
            {discoveryError === null ? null : (
              <div className="mt-3 text-sm text-red-700" role="alert">
                <p>{discoveryError}</p>
                <button
                  className="mt-2 font-semibold underline underline-offset-2"
                  onClick={() => {
                    setDiscoveryError(null);
                    setLoadingVersions(true);
                    setDatasetRevision((current) => current + 1);
                  }}
                  type="button"
                >
                  Retry document discovery
                </button>
              </div>
            )}
            {datasetTotal > DATASET_PAGE_SIZE ? (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
                <span className="text-muted-foreground">
                  Datasets {datasetOffset + 1}–
                  {Math.min(datasetOffset + DATASET_PAGE_SIZE, datasetTotal)} of{" "}
                  {datasetTotal}
                </span>
                <div className="flex gap-2">
                  <button
                    className={secondaryButtonClassName}
                    disabled={loadingVersions || datasetOffset === 0 || submitting}
                    onClick={() => {
                      setDiscoveryError(null);
                      setLoadingVersions(true);
                      setDatasetOffset((current) =>
                        Math.max(0, current - DATASET_PAGE_SIZE),
                      );
                    }}
                    type="button"
                  >
                    Previous datasets
                  </button>
                  <button
                    className={secondaryButtonClassName}
                    disabled={
                      loadingVersions ||
                      datasetOffset + DATASET_PAGE_SIZE >= datasetTotal ||
                      submitting
                    }
                    onClick={() => {
                      setDiscoveryError(null);
                      setLoadingVersions(true);
                      setDatasetOffset((current) => current + DATASET_PAGE_SIZE);
                    }}
                    type="button"
                  >
                    Next datasets
                  </button>
                </div>
              </div>
            ) : null}
            {selected.length > 0 ? (
              <p className="mt-3 text-sm text-muted-foreground">
                {selected.length} version{selected.length === 1 ? "" : "s"} selected
                across dataset pages.
              </p>
            ) : null}
          </fieldset>
          {error === null ? null : (
            <p
              className="mt-5 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
              role="alert"
            >
              {error}
            </p>
          )}
          {submitting ? (
            <p
              aria-live="polite"
              className="mt-4 text-sm font-medium text-link"
              role="status"
            >
              Creating knowledge base and attaching versions…
            </p>
          ) : null}
          <div className="mt-6 flex justify-end gap-3 border-t border-border pt-5">
            <Link className={secondaryButtonClassName} to="/knowledge">
              Cancel
            </Link>
            <button
              className={primaryButtonClassName}
              disabled={submitting || loadingVersions || discoveryError !== null}
              type="submit"
            >
              {submitting ? "Creating…" : "Create knowledge base"}
            </button>
          </div>
        </LifecycleCard>
      </form>
    </section>
  );
}
