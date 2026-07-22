import { useEffect, useRef, useState, type FormEvent, type ReactElement } from "react";
import { useParams } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import {
  archiveConversation,
  cancelChatMessage,
  getConversation,
  listLatestConversationMessages,
  listConversationMessages,
  submitChatMessage,
  type ChatMessage,
  type ChatMessagePage,
  type ChatMessageSubmission,
  type ConversationSummary,
} from "../../api/chat";
import {
  LifecycleStatus,
  terminalMessageStatuses,
} from "../../components/dataRag/DataRagUi";
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

const POLL_INTERVAL_MS = 2_000;
const MESSAGE_PAGE_SIZE = 100;

function mergeSubmittedExchange(
  current: ChatMessagePage | null,
  submission: ChatMessageSubmission,
): ChatMessagePage {
  const additions = [submission.user_message, submission.assistant_message];
  if (current === null) {
    return {
      items: additions,
      limit: MESSAGE_PAGE_SIZE,
      offset: 0,
      total: additions.length,
    };
  }
  const existingIds = new Set(current.items.map((message) => message.message_id));
  const uniqueAdditions = additions.filter(
    (message) => !existingIds.has(message.message_id),
  );
  const total = current.total + uniqueAdditions.length;
  const offset =
    Math.floor(Math.max(0, total - 1) / MESSAGE_PAGE_SIZE) * MESSAGE_PAGE_SIZE;
  const combined = [...current.items, ...uniqueAdditions];
  const relativeOffset = Math.max(0, offset - current.offset);
  return {
    items:
      relativeOffset >= combined.length
        ? uniqueAdditions
        : combined.slice(relativeOffset, relativeOffset + MESSAGE_PAGE_SIZE),
    limit: MESSAGE_PAGE_SIZE,
    offset,
    total,
  };
}

export function ConversationPage(): ReactElement {
  const { conversationId = "" } = useParams();
  const [conversation, setConversation] = useState<ConversationSummary | null>(null);
  const [messages, setMessages] = useState<ChatMessagePage | null>(null);
  const [messageOffset, setMessageOffset] = useState<number | null>(null);
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [executionError, setExecutionError] = useState<string | null>(null);
  const [mutating, setMutating] = useState(false);
  const messageKey = useRef(crypto.randomUUID());

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    const load = async (): Promise<void> => {
      try {
        const [nextConversation, nextMessages] = await Promise.all([
          getConversation(conversationId, controller.signal),
          messageOffset === null
            ? listLatestConversationMessages(conversationId, {
                limit: MESSAGE_PAGE_SIZE,
                signal: controller.signal,
              })
            : listConversationMessages(conversationId, {
                limit: MESSAGE_PAGE_SIZE,
                offset: messageOffset,
                signal: controller.signal,
              }),
        ]);
        if (controller.signal.aborted) return;
        setConversation(nextConversation);
        setMessages(nextMessages);
        setError(null);
        setLoading(false);
        if (
          messageOffset === null &&
          nextMessages.items.some(
            (message) => !terminalMessageStatuses.has(message.status),
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
  }, [conversationId, messageOffset, revision]);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (submitting || !content.trim()) return;
    setSubmitting(true);
    setExecutionError(null);
    try {
      const submission = await submitChatMessage(
        conversationId,
        content.trim(),
        messageKey.current,
      );
      messageKey.current = crypto.randomUUID();
      setContent("");
      setMessageOffset(null);
      setMessages((current) => mergeSubmittedExchange(current, submission));
      setRevision((value) => value + 1);
    } catch (caught) {
      setExecutionError(hierarchyError(caught));
    } finally {
      setSubmitting(false);
    }
  };

  const mutate = async (operation: () => Promise<unknown>): Promise<void> => {
    if (mutating) return;
    setMutating(true);
    setExecutionError(null);
    try {
      await operation();
      setRevision((value) => value + 1);
    } catch (caught) {
      setExecutionError(hierarchyError(caught));
    } finally {
      setMutating(false);
    }
  };

  if (loading && conversation === null)
    return <LoadingSkeleton label="Loading conversation" />;
  if (error !== null || conversation === null)
    return (
      <InlineError
        message={error ?? "The requested conversation is unavailable."}
        onRetry={() => setRevision((value) => value + 1)}
      />
    );

  return (
    <section aria-labelledby="conversation-heading">
      <Breadcrumbs
        items={[{ label: "AI Assistant", to: "/chat" }, { label: conversation.title }]}
      />
      <PageHeader
        actions={
          conversation.status === "active" ? (
            <button
              className={secondaryButtonClassName}
              disabled={mutating}
              onClick={() =>
                void mutate(() => archiveConversation(conversation.conversation_id))
              }
              type="button"
            >
              {mutating ? "Archiving…" : "Archive conversation"}
            </button>
          ) : undefined
        }
        description="Grounded responses cite registered evidence. Retrieved documents are treated as untrusted data, not instructions."
        eyebrow="AI Assistant"
        headingId="conversation-heading"
        title={conversation.title}
      />
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <LifecycleStatus status={conversation.status} />
        <span className="break-all text-xs text-muted-foreground">
          Knowledge base {conversation.knowledge_base_id}
        </span>
      </div>
      <div
        aria-label="Conversation messages"
        aria-relevant="additions"
        className="mt-6 space-y-4"
        role="log"
      >
        {messages === null || messages.items.length === 0 ? (
          <EmptyState
            description="Ask a question whose answer can be supported by registered evidence."
            title="No messages"
          />
        ) : (
          messages.items.map((message) => (
            <MessageCard
              busy={mutating}
              key={message.message_id}
              message={message}
              onCancel={() => void mutate(() => cancelChatMessage(message.message_id))}
            />
          ))
        )}
      </div>
      {messages === null ? null : (
        <PaginationControls
          limit={messages.limit}
          offset={messages.offset}
          onPageChange={(nextOffset) => {
            setLoading(true);
            setMessageOffset(
              nextOffset + MESSAGE_PAGE_SIZE >= messages.total ? null : nextOffset,
            );
          }}
          total={messages.total}
        />
      )}
      {conversation.status === "active" ? (
        <form
          className="sticky bottom-3 mt-6 rounded-lg border border-border bg-card p-4 shadow-panel"
          onSubmit={(event) => void submit(event)}
        >
          <label className="text-sm font-medium">
            Message
            <textarea
              className="mt-1 min-h-24 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
              disabled={submitting}
              maxLength={4000}
              onChange={(event) => {
                setContent(event.target.value);
                setExecutionError(null);
              }}
              placeholder="Ask a question about the registered evidence…"
              required
              value={content}
            />
          </label>
          {executionError === null ? null : (
            <p className="mt-3 text-sm text-red-700" role="alert">
              {executionError}
            </p>
          )}
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              No browsing, tools, or autonomous actions.
            </p>
            <button
              className={primaryButtonClassName}
              disabled={submitting || !content.trim()}
              type="submit"
            >
              {submitting ? "Submitting…" : "Send grounded question"}
            </button>
          </div>
        </form>
      ) : (
        <div className="mt-6">
          <InlineNotice>This conversation is archived and read-only.</InlineNotice>
        </div>
      )}
    </section>
  );
}

function MessageCard({
  busy,
  message,
  onCancel,
}: {
  readonly busy: boolean;
  readonly message: ChatMessage;
  readonly onCancel: () => void;
}): ReactElement {
  const active = !terminalMessageStatuses.has(message.status);
  return (
    <article
      aria-label={`${message.role} message`}
      className={`rounded-lg border p-5 shadow-panel ${message.role === "assistant" ? "border-purple-200 bg-card" : "ml-auto max-w-3xl border-border bg-elevated"}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm font-semibold capitalize">{message.role}</p>
        <div className="flex items-center gap-2">
          <LifecycleStatus status={message.status} />
          {active ? (
            <button
              className="text-xs font-semibold text-link hover:underline disabled:opacity-60"
              disabled={busy}
              onClick={onCancel}
              type="button"
            >
              Cancel
            </button>
          ) : null}
        </div>
      </div>
      {message.content ? (
        <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6">
          {message.content}
        </p>
      ) : active ? (
        <p className="mt-3 text-sm text-muted-foreground" role="status">
          {message.status.replaceAll("_", " ")}…
        </p>
      ) : null}
      {message.safe_error_message === null ? null : (
        <p className="mt-3 text-sm text-red-700" role="alert">
          {message.safe_error_message}
        </p>
      )}
      {message.grounded_outcome === "insufficient_evidence" ? (
        <p className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          The registered evidence was insufficient to support an answer.
        </p>
      ) : null}
      {message.citations.length > 0 ? (
        <section className="mt-4 border-t border-border pt-4" aria-label="Citations">
          <h4 className="text-sm font-semibold">Registered sources</h4>
          <ol className="mt-2 space-y-2">
            {message.citations.map((citation) => (
              <li className="rounded-md bg-elevated p-3" key={citation.citation_id}>
                <p className="text-sm font-semibold">
                  [{citation.rank}] {citation.document_title}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {citation.page_number === null
                    ? "Registered document"
                    : `Page ${citation.page_number}`}
                  {citation.section === null ? "" : ` · ${citation.section}`}
                </p>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
                  {citation.excerpt}
                </p>
              </li>
            ))}
          </ol>
        </section>
      ) : null}
      <p className="mt-3 text-xs text-muted-foreground">
        {formatDate(message.created_at)}
      </p>
    </article>
  );
}
