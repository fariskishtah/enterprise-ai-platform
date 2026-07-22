import { useEffect, useState, type FormEvent, type ReactElement } from "react";
import { useLocation, useParams } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import { listAllDatasetVersions, listDatasets } from "../../api/datasets";
import {
  attachDatasetVersion,
  buildKnowledgeBase,
  cancelKnowledgeBaseBuild,
  detachDatasetVersion,
  getKnowledgeBase,
  listKnowledgeBaseBuilds,
  searchKnowledgeBase,
  type KnowledgeBaseDetail,
  type RAGIndexBuildPage,
  type RAGSearchResponse,
} from "../../api/rag";
import {
  KeyValueGrid,
  LifecycleCard,
  LifecycleStatus,
  SafeMetadata,
  terminalBuildStatuses,
} from "../../components/dataRag/DataRagUi";
import {
  Breadcrumbs,
  EmptyState,
  InlineError,
  InlineNotice,
  LoadingSkeleton,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatDate, hierarchyError } from "../hierarchy/shared";

const POLL_INTERVAL_MS = 3_000;
const DATASET_PAGE_SIZE = 20;

interface ReadyVersionOption {
  readonly id: string;
  readonly label: string;
}

export function KnowledgeBaseDetailPage(): ReactElement {
  const { knowledgeBaseId = "" } = useParams();
  const location = useLocation();
  const [knowledgeBase, setKnowledgeBase] = useState<KnowledgeBaseDetail | null>(null);
  const [builds, setBuilds] = useState<RAGIndexBuildPage | null>(null);
  const [availableVersions, setAvailableVersions] = useState<
    readonly ReadyVersionOption[]
  >([]);
  const [selectedVersion, setSelectedVersion] = useState("");
  const [datasetOffset, setDatasetOffset] = useState(0);
  const [datasetTotal, setDatasetTotal] = useState(0);
  const [versionsLoading, setVersionsLoading] = useState(true);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  const [versionsRevision, setVersionsRevision] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mutating, setMutating] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchResult, setSearchResult] = useState<RAGSearchResponse | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async (): Promise<void> => {
      try {
        const [nextKnowledgeBase, nextBuilds] = await Promise.all([
          getKnowledgeBase(knowledgeBaseId, controller.signal),
          listKnowledgeBaseBuilds(knowledgeBaseId, {
            limit: 20,
            offset: 0,
            signal: controller.signal,
          }),
        ]);
        if (controller.signal.aborted) return;
        setKnowledgeBase(nextKnowledgeBase);
        setBuilds(nextBuilds);
        setError(null);
        setLoading(false);
        if (
          nextKnowledgeBase.status === "indexing" ||
          nextBuilds.items.some((build) => !terminalBuildStatuses.has(build.status))
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
  }, [knowledgeBaseId, revision]);

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
        const pages = await Promise.all(
          datasets.items.map(async (dataset) => ({
            dataset,
            versions: await listAllDatasetVersions(dataset.id, {
              signal: controller.signal,
            }),
          })),
        );
        if (controller.signal.aborted) return;
        setDatasetTotal(datasets.total);
        setAvailableVersions(
          pages.flatMap(({ dataset, versions }) =>
            versions
              .filter((version) => version.status === "ready")
              .map((version) => ({
                id: version.id,
                label: `${dataset.name} · version ${version.version_number}`,
              })),
          ),
        );
        setVersionsError(null);
        setVersionsLoading(false);
      } catch (caught) {
        if (!isRequestCancelled(caught, controller.signal)) {
          setVersionsError(hierarchyError(caught));
          setVersionsLoading(false);
        }
      }
    };
    void load();
    return () => controller.abort();
  }, [datasetOffset, versionsRevision]);

  const mutate = async (operation: () => Promise<unknown>): Promise<void> => {
    if (mutating) return;
    setMutating(true);
    setMutationError(null);
    try {
      await operation();
      setRevision((value) => value + 1);
    } catch (caught) {
      setMutationError(hierarchyError(caught));
    } finally {
      setMutating(false);
    }
  };

  const build = (): Promise<void> =>
    mutate(async () => {
      await buildKnowledgeBase(knowledgeBaseId);
    });

  const search = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (searching) return;
    setSearching(true);
    setSearchError(null);
    setSearchResult(null);
    try {
      setSearchResult(await searchKnowledgeBase(knowledgeBaseId, query.trim(), 5));
    } catch (caught) {
      setSearchError(hierarchyError(caught));
    } finally {
      setSearching(false);
    }
  };

  if (loading && knowledgeBase === null)
    return <LoadingSkeleton label="Loading knowledge base" />;
  if (error !== null || knowledgeBase === null)
    return (
      <InlineError
        message={error ?? "The requested knowledge base is unavailable."}
        onRetry={() => setRevision((value) => value + 1)}
      />
    );
  const activeBuild =
    builds?.items.find((build) => !terminalBuildStatuses.has(build.status)) ?? null;
  const attachedIds = new Set(
    knowledgeBase.dataset_versions.map((item) => item.dataset_version_id),
  );
  const attachable = availableVersions.filter((item) => !attachedIds.has(item.id));

  return (
    <section aria-labelledby="knowledge-detail-heading">
      <Breadcrumbs
        items={[
          { label: "Knowledge Bases", to: "/knowledge" },
          { label: knowledgeBase.name },
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
          knowledgeBase.status !== "archived" ? (
            activeBuild === null ? (
              <button
                className={primaryButtonClassName}
                disabled={mutating || knowledgeBase.dataset_versions.length === 0}
                onClick={() => void build()}
                type="button"
              >
                {mutating ? "Starting…" : "Build index"}
              </button>
            ) : (
              <button
                className={secondaryButtonClassName}
                disabled={mutating}
                onClick={() =>
                  void mutate(() => cancelKnowledgeBaseBuild(knowledgeBaseId))
                }
                type="button"
              >
                {mutating ? "Cancelling…" : "Cancel build"}
              </button>
            )
          ) : undefined
        }
        description={knowledgeBase.description ?? "No description provided."}
        eyebrow="Knowledge base"
        headingId="knowledge-detail-heading"
        title={knowledgeBase.name}
      />
      <div className="mt-5">
        <LifecycleStatus status={knowledgeBase.status} />
      </div>
      {mutationError === null ? null : (
        <p
          className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
          role="alert"
        >
          {mutationError}
        </p>
      )}
      {knowledgeBase.safe_error_message === null ? null : (
        <p
          className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
          role="alert"
        >
          {knowledgeBase.safe_error_message}
        </p>
      )}
      <div className="mt-6">
        <LifecycleCard>
          <KeyValueGrid
            items={[
              { label: "Embedding provider", value: knowledgeBase.embedding_provider },
              { label: "Embedding model", value: knowledgeBase.embedding_model },
              { label: "Dimension", value: knowledgeBase.embedding_dimension },
              {
                label: "Attached versions",
                value: knowledgeBase.attached_dataset_version_count,
              },
              {
                label: "Indexed documents",
                value: knowledgeBase.indexed_document_count,
              },
              { label: "Indexed chunks", value: knowledgeBase.indexed_chunk_count },
              { label: "Created", value: formatDate(knowledgeBase.created_at) },
              { label: "Updated", value: formatDate(knowledgeBase.updated_at) },
            ]}
          />
        </LifecycleCard>
      </div>
      <div className="mt-7 grid gap-5 lg:grid-cols-2">
        <LifecycleCard>
          <h3 className="text-lg font-semibold">Registered evidence</h3>
          {knowledgeBase.dataset_versions.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">
              Attach a ready document dataset version before building.
            </p>
          ) : (
            <ul className="mt-3 space-y-2">
              {knowledgeBase.dataset_versions.map((attachment) => (
                <li
                  className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-elevated p-3"
                  key={attachment.dataset_version_id}
                >
                  <div className="min-w-0">
                    <p className="break-all text-sm font-semibold">
                      {attachment.dataset_version_id}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Attached {formatDate(attachment.attached_at)}
                    </p>
                  </div>
                  <button
                    className={secondaryButtonClassName}
                    disabled={mutating || activeBuild !== null}
                    onClick={() =>
                      void mutate(() =>
                        detachDatasetVersion(
                          knowledgeBaseId,
                          attachment.dataset_version_id,
                        ),
                      )
                    }
                    type="button"
                  >
                    Detach
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <select
              aria-label="Ready document version"
              className="min-w-0 flex-1 rounded-md border border-border-strong bg-elevated px-3 py-2 text-sm"
              disabled={
                mutating ||
                versionsLoading ||
                versionsError !== null ||
                activeBuild !== null
              }
              onChange={(event) => setSelectedVersion(event.target.value)}
              value={selectedVersion}
            >
              <option value="">Select a ready version</option>
              {attachable.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
            <button
              className={secondaryButtonClassName}
              disabled={
                mutating ||
                versionsLoading ||
                versionsError !== null ||
                selectedVersion === "" ||
                activeBuild !== null
              }
              onClick={() =>
                void mutate(async () => {
                  await attachDatasetVersion(knowledgeBaseId, selectedVersion);
                  setSelectedVersion("");
                })
              }
              type="button"
            >
              Attach version
            </button>
          </div>
          {versionsError === null ? null : (
            <div className="mt-3 text-sm text-red-700" role="alert">
              <p>{versionsError}</p>
              <button
                className="mt-2 font-semibold underline underline-offset-2"
                onClick={() => {
                  setVersionsError(null);
                  setVersionsLoading(true);
                  setVersionsRevision((current) => current + 1);
                }}
                type="button"
              >
                Retry document discovery
              </button>
            </div>
          )}
          {datasetTotal > DATASET_PAGE_SIZE ? (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="text-muted-foreground">
                Datasets {datasetOffset + 1}–
                {Math.min(datasetOffset + DATASET_PAGE_SIZE, datasetTotal)} of{" "}
                {datasetTotal}
              </span>
              <div className="flex gap-2">
                <button
                  className={secondaryButtonClassName}
                  disabled={
                    mutating ||
                    versionsLoading ||
                    datasetOffset === 0 ||
                    activeBuild !== null
                  }
                  onClick={() => {
                    setSelectedVersion("");
                    setVersionsError(null);
                    setVersionsLoading(true);
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
                    mutating ||
                    versionsLoading ||
                    datasetOffset + DATASET_PAGE_SIZE >= datasetTotal ||
                    activeBuild !== null
                  }
                  onClick={() => {
                    setSelectedVersion("");
                    setVersionsError(null);
                    setVersionsLoading(true);
                    setDatasetOffset((current) => current + DATASET_PAGE_SIZE);
                  }}
                  type="button"
                >
                  Next datasets
                </button>
              </div>
            </div>
          ) : null}
        </LifecycleCard>
        <LifecycleCard>
          <h3 className="text-lg font-semibold">Chunking configuration</h3>
          <div className="mt-3">
            <SafeMetadata value={knowledgeBase.chunking_configuration} />
          </div>
        </LifecycleCard>
      </div>
      <section className="mt-7" aria-labelledby="index-builds-heading">
        <h3 className="text-lg font-semibold" id="index-builds-heading">
          Index builds
        </h3>
        <div className="mt-4">
          {builds === null || builds.items.length === 0 ? (
            <EmptyState
              description="Start a build after attaching registered document versions."
              title="No index builds"
            />
          ) : (
            <div
              aria-label="Index build history"
              className="overflow-x-auto rounded-lg border border-border bg-card"
              role="region"
              tabIndex={0}
            >
              <table className="min-w-full divide-y divide-border text-left text-sm">
                <thead className="bg-muted text-xs uppercase">
                  <tr>
                    <th className="px-4 py-3">Build</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Documents</th>
                    <th className="px-4 py-3">Chunks</th>
                    <th className="px-4 py-3">Result</th>
                    <th className="px-4 py-3">Created</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {builds.items.map((buildItem) => (
                    <tr key={buildItem.index_build_id}>
                      <td className="max-w-xs break-all px-4 py-3 font-mono text-xs">
                        {buildItem.index_build_id}
                      </td>
                      <td className="px-4 py-3">
                        <LifecycleStatus status={buildItem.status} />
                      </td>
                      <td className="px-4 py-3">{buildItem.indexed_document_count}</td>
                      <td className="px-4 py-3">{buildItem.indexed_chunk_count}</td>
                      <td className="max-w-sm px-4 py-3 text-muted-foreground">
                        {buildItem.safe_error_message ??
                          `${buildItem.embedding_count} embeddings`}
                      </td>
                      <td className="px-4 py-3">{formatDate(buildItem.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
      <section className="mt-7" aria-labelledby="retrieval-test-heading">
        <h3 className="text-lg font-semibold" id="retrieval-test-heading">
          Retrieval test
        </h3>
        <form className="mt-4" onSubmit={(event) => void search(event)}>
          <LifecycleCard>
            <label className="text-sm font-medium">
              Grounded query
              <textarea
                className="mt-1 min-h-24 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                disabled={searching || knowledgeBase.status !== "ready"}
                maxLength={4000}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setSearchError(null);
                }}
                required
                value={query}
              />
            </label>
            <button
              className={`${primaryButtonClassName} mt-4`}
              disabled={searching || knowledgeBase.status !== "ready" || !query.trim()}
              type="submit"
            >
              {searching ? "Searching…" : "Search registered evidence"}
            </button>
            {searchError === null ? null : (
              <p className="mt-4 text-sm text-red-700" role="alert">
                {searchError}
              </p>
            )}
            {searchResult === null ? null : searchResult.results.length === 0 ? (
              <p className="mt-4 text-sm font-medium" role="status">
                No sufficiently relevant registered evidence was found.
              </p>
            ) : (
              <ol className="mt-5 space-y-3" aria-label="Retrieval citations">
                {searchResult.results.map((result) => (
                  <li
                    className="rounded-md border border-border bg-elevated p-4"
                    key={result.chunk_id}
                  >
                    <p className="text-sm font-semibold">
                      [{result.rank}] {result.document_title}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Score {result.score.toFixed(4)}
                      {result.page_number === null
                        ? ""
                        : ` · Page ${result.page_number}`}
                      {result.section === null ? "" : ` · ${result.section}`}
                    </p>
                    <p className="mt-3 whitespace-pre-wrap text-sm leading-6">
                      {result.excerpt}
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </LifecycleCard>
        </form>
      </section>
    </section>
  );
}
