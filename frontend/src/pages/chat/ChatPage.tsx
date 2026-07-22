import { useEffect, useState, type FormEvent, type ReactElement } from "react";
import { Link, useNavigate } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  createConversation,
  listConversations,
  type ConversationPage,
  type ConversationStatus,
} from "../../api/chat";
import { listKnowledgeBases, type KnowledgeBaseSummary } from "../../api/rag";
import { LifecycleStatus } from "../../components/dataRag/DataRagUi";
import {
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
const KNOWLEDGE_BASE_PAGE_SIZE = 20;

export function ChatPage(): ReactElement {
  const navigate = useNavigate();
  const [page, setPage] = useState<ConversationPage | null>(null);
  const [knowledgeBases, setKnowledgeBases] = useState<readonly KnowledgeBaseSummary[]>(
    [],
  );
  const [knowledgeBaseOffset, setKnowledgeBaseOffset] = useState(0);
  const [knowledgeBaseTotal, setKnowledgeBaseTotal] = useState(0);
  const [knowledgeBaseLoading, setKnowledgeBaseLoading] = useState(true);
  const [knowledgeBaseError, setKnowledgeBaseError] = useState<string | null>(null);
  const [knowledgeBaseRevision, setKnowledgeBaseRevision] = useState(0);
  const [status, setStatus] = useState<ConversationStatus | "">("");
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [knowledgeBaseId, setKnowledgeBaseId] = useState("");
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listConversations({
      limit: PAGE_SIZE,
      offset,
      signal: controller.signal,
      status: status || undefined,
    })
      .then((conversations) => {
        if (controller.signal.aborted) return;
        setPage(conversations);
        setError(null);
        setLoading(false);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) {
          setError(hierarchyError(caught));
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [offset, revision, status]);

  useEffect(() => {
    const controller = new AbortController();
    listKnowledgeBases({
      limit: KNOWLEDGE_BASE_PAGE_SIZE,
      offset: knowledgeBaseOffset,
      signal: controller.signal,
      status: "ready",
    })
      .then((bases) => {
        if (controller.signal.aborted) return;
        setKnowledgeBases(bases.items);
        setKnowledgeBaseTotal(bases.total);
        setKnowledgeBaseError(null);
        setKnowledgeBaseLoading(false);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) {
          setKnowledgeBaseError(hierarchyError(caught));
          setKnowledgeBaseLoading(false);
        }
      });
    return () => controller.abort();
  }, [knowledgeBaseOffset, knowledgeBaseRevision]);

  const create = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (creating) return;
    setCreating(true);
    setCreateError(null);
    try {
      const conversation = await createConversation({
        knowledge_base_id: knowledgeBaseId,
        title: title.trim() || undefined,
      });
      navigate(`/chat/${conversation.conversation_id}`);
    } catch (caught) {
      setCreateError(hierarchyError(caught));
      setCreating(false);
    }
  };

  return (
    <section aria-labelledby="chat-heading">
      <PageHeader
        description="Ask grounded questions against one ready authorized knowledge base. The assistant cannot browse or invoke tools."
        eyebrow="Enterprise RAG"
        headingId="chat-heading"
        title="AI Assistant"
      />
      <div className="mt-6 grid gap-6 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <form
          aria-label="New grounded conversation"
          className="h-fit rounded-lg border border-border bg-card p-5 shadow-panel"
          onSubmit={(event) => void create(event)}
        >
          <h3 className="text-lg font-semibold">New conversation</h3>
          <div className="mt-4">
            <InlineNotice>
              Answers distinguish retrieved evidence from generated explanation and cite
              registered sources.
            </InlineNotice>
          </div>
          <label className="mt-4 block text-sm font-medium">
            Knowledge base
            <select
              className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
              disabled={creating || knowledgeBaseLoading || knowledgeBaseError !== null}
              onChange={(event) => setKnowledgeBaseId(event.target.value)}
              required
              value={knowledgeBaseId}
            >
              <option value="">Select a ready knowledge base</option>
              {knowledgeBases.map((base) => (
                <option key={base.knowledge_base_id} value={base.knowledge_base_id}>
                  {base.name}
                </option>
              ))}
            </select>
          </label>
          {knowledgeBaseLoading ? (
            <p className="mt-2 text-xs text-muted-foreground" role="status">
              Loading ready knowledge bases…
            </p>
          ) : null}
          {knowledgeBaseError === null ? null : (
            <div className="mt-3 text-sm text-red-700" role="alert">
              <p>{knowledgeBaseError}</p>
              <button
                className="mt-2 font-semibold underline underline-offset-2"
                onClick={() => {
                  setKnowledgeBaseLoading(true);
                  setKnowledgeBaseRevision((current) => current + 1);
                }}
                type="button"
              >
                Retry knowledge-base discovery
              </button>
            </div>
          )}
          {knowledgeBaseTotal > KNOWLEDGE_BASE_PAGE_SIZE ? (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
              <span className="text-muted-foreground">
                Knowledge bases {knowledgeBaseOffset + 1}–
                {Math.min(
                  knowledgeBaseOffset + KNOWLEDGE_BASE_PAGE_SIZE,
                  knowledgeBaseTotal,
                )}{" "}
                of {knowledgeBaseTotal}
              </span>
              <div className="flex gap-2">
                <button
                  className={secondaryButtonClassName}
                  disabled={
                    creating || knowledgeBaseLoading || knowledgeBaseOffset === 0
                  }
                  onClick={() => {
                    setKnowledgeBaseId("");
                    setKnowledgeBaseLoading(true);
                    setKnowledgeBaseOffset((current) =>
                      Math.max(0, current - KNOWLEDGE_BASE_PAGE_SIZE),
                    );
                  }}
                  type="button"
                >
                  Previous
                </button>
                <button
                  className={secondaryButtonClassName}
                  disabled={
                    creating ||
                    knowledgeBaseLoading ||
                    knowledgeBaseOffset + KNOWLEDGE_BASE_PAGE_SIZE >= knowledgeBaseTotal
                  }
                  onClick={() => {
                    setKnowledgeBaseId("");
                    setKnowledgeBaseLoading(true);
                    setKnowledgeBaseOffset(
                      (current) => current + KNOWLEDGE_BASE_PAGE_SIZE,
                    );
                  }}
                  type="button"
                >
                  Next
                </button>
              </div>
            </div>
          ) : null}
          <label className="mt-4 block text-sm font-medium">
            Title (optional)
            <input
              className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
              disabled={creating}
              maxLength={255}
              onChange={(event) => setTitle(event.target.value)}
              value={title}
            />
          </label>
          {createError === null ? null : (
            <p className="mt-4 text-sm text-red-700" role="alert">
              {createError}
            </p>
          )}
          <button
            className={`${primaryButtonClassName} mt-5 w-full`}
            disabled={
              creating ||
              knowledgeBaseLoading ||
              knowledgeBaseError !== null ||
              knowledgeBaseId === ""
            }
            type="submit"
          >
            {creating ? "Creating…" : "Start conversation"}
          </button>
        </form>
        <div>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <h3 className="text-lg font-semibold">Conversations</h3>
            <label className="text-sm font-medium">
              Status
              <select
                className="ml-2 rounded-md border border-border-strong bg-elevated px-3 py-2"
                onChange={(event) => {
                  setLoading(true);
                  setOffset(0);
                  setStatus(event.target.value as ConversationStatus | "");
                }}
                value={status}
              >
                <option value="">All</option>
                <option value="active">Active</option>
                <option value="archived">Archived</option>
              </select>
            </label>
          </div>
          <div className="mt-4">
            {loading && page === null ? (
              <LoadingSkeleton label="Loading conversations" />
            ) : error !== null ? (
              <InlineError
                message={error}
                onRetry={() => setRevision((value) => value + 1)}
              />
            ) : page === null || page.items.length === 0 ? (
              <EmptyState
                description="Choose a ready knowledge base to start a grounded conversation."
                title="No conversations"
              />
            ) : (
              <>
                <ul className="space-y-3">
                  {page.items.map((conversation) => (
                    <li
                      className="rounded-lg border border-border bg-card p-4 shadow-panel"
                      key={conversation.conversation_id}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <Link
                          className="break-words font-semibold text-link hover:underline"
                          to={`/chat/${conversation.conversation_id}`}
                        >
                          {conversation.title}
                        </Link>
                        <LifecycleStatus status={conversation.status} />
                      </div>
                      <p className="mt-2 break-all text-xs text-muted-foreground">
                        Knowledge base {conversation.knowledge_base_id}
                      </p>
                      <p className="mt-2 text-xs text-muted-foreground">
                        Updated {formatDate(conversation.updated_at)}
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
        </div>
      </div>
    </section>
  );
}
