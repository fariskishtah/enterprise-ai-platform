import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  listKnowledgeBases,
  type KnowledgeBasePage,
  type KnowledgeBaseStatus,
} from "../../api/rag";
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

export function KnowledgeBasesPage(): ReactElement {
  const [page, setPage] = useState<KnowledgeBasePage | null>(null);
  const [status, setStatus] = useState<KnowledgeBaseStatus | "">("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listKnowledgeBases({
      limit: PAGE_SIZE,
      offset,
      signal: controller.signal,
      status: status || undefined,
    })
      .then((result) => {
        if (controller.signal.aborted) return;
        setPage(result);
        setLoading(false);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) {
          setError(hierarchyError(caught));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [offset, revision, status]);

  return (
    <section aria-labelledby="knowledge-heading">
      <PageHeader
        actions={
          <Link className={primaryButtonClassName} to="/knowledge/new">
            Create knowledge base
          </Link>
        }
        description="Build authorization-aware indexes from ready registered document versions."
        eyebrow="Grounded AI"
        headingId="knowledge-heading"
        title="Knowledge Bases"
      />
      <label className="mt-6 block max-w-xs text-sm font-medium text-foreground">
        Status
        <select
          className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
          onChange={(event) => {
            setLoading(true);
            setOffset(0);
            setStatus(event.target.value as KnowledgeBaseStatus | "");
          }}
          value={status}
        >
          <option value="">All statuses</option>
          <option value="draft">Draft</option>
          <option value="indexing">Indexing</option>
          <option value="ready">Ready</option>
          <option value="failed">Failed</option>
          <option value="archived">Archived</option>
        </select>
      </label>
      <div className="mt-5">
        {loading && page === null ? (
          <LoadingSkeleton label="Loading knowledge bases" />
        ) : error !== null ? (
          <InlineError
            message={error}
            onRetry={() => setRevision((value) => value + 1)}
          />
        ) : page === null || page.items.length === 0 ? (
          <EmptyState
            action={
              <Link className={primaryButtonClassName} to="/knowledge/new">
                Create knowledge base
              </Link>
            }
            description="Create a knowledge base and attach one or more ready document dataset versions."
            title="No knowledge bases"
          />
        ) : (
          <>
            <ul className="grid gap-4 lg:grid-cols-2">
              {page.items.map((knowledgeBase) => (
                <li
                  className="rounded-lg border border-border bg-card p-5 shadow-panel"
                  key={knowledgeBase.knowledge_base_id}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        className="break-words text-lg font-semibold text-link hover:underline"
                        to={`/knowledge/${knowledgeBase.knowledge_base_id}`}
                      >
                        {knowledgeBase.name}
                      </Link>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {knowledgeBase.embedding_provider} ·{" "}
                        {knowledgeBase.embedding_model}
                      </p>
                    </div>
                    <LifecycleStatus status={knowledgeBase.status} />
                  </div>
                  <p className="mt-4 text-sm text-secondary-foreground">
                    {knowledgeBase.description ?? "No description provided."}
                  </p>
                  <p className="mt-4 text-xs text-muted-foreground">
                    {knowledgeBase.attached_dataset_version_count} attached versions ·
                    Updated {formatDate(knowledgeBase.updated_at)}
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
