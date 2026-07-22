import { apiRequest } from "./client";

export type ConversationStatus = "active" | "archived";
export type ChatMessageStatus =
  "cancelled" | "failed" | "generating" | "queued" | "retrieving" | "succeeded";
export type ChatMessageRole = "assistant" | "user";

export interface ConversationSummary {
  readonly conversation_id: string;
  readonly knowledge_base_id: string;
  readonly title: string;
  readonly status: ConversationStatus;
  readonly created_at: string;
  readonly updated_at: string;
  readonly archived_at: string | null;
}

export interface ConversationPage {
  readonly items: readonly ConversationSummary[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface ChatCitation {
  readonly citation_id: string;
  readonly chunk_id: string;
  readonly document_id: string;
  readonly dataset_version_id: string;
  readonly rank: number;
  readonly score: number;
  readonly excerpt: string;
  readonly document_title: string;
  readonly page_number: number | null;
  readonly section: string | null;
}

export interface ChatMessage {
  readonly message_id: string;
  readonly conversation_id: string;
  readonly reply_to_message_id: string | null;
  readonly role: ChatMessageRole;
  readonly content: string;
  readonly status: ChatMessageStatus;
  readonly grounded_outcome: "grounded" | "insufficient_evidence" | null;
  readonly generation_provider: string | null;
  readonly generation_model: string | null;
  readonly citations: readonly ChatCitation[];
  readonly created_at: string;
  readonly completed_at: string | null;
  readonly error_code: string | null;
  readonly safe_error_message: string | null;
}

export interface ChatMessagePage {
  readonly items: readonly ChatMessage[];
  readonly total: number;
  readonly limit: number;
  readonly offset: number;
}

export interface ChatMessageSubmission {
  readonly user_message: ChatMessage;
  readonly assistant_message: ChatMessage;
}

function pageQuery(limit: number, offset: number): string {
  return `?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`;
}

export function listConversations(
  options: {
    readonly limit?: number;
    readonly offset?: number;
    readonly signal?: AbortSignal;
    readonly status?: ConversationStatus;
  } = {},
): Promise<ConversationPage> {
  const query = new URLSearchParams({
    limit: String(options.limit ?? 20),
    offset: String(options.offset ?? 0),
  });
  if (options.status) query.set("status", options.status);
  return apiRequest(`/ai/chat/conversations?${query}`, { signal: options.signal });
}

export const createConversation = (payload: {
  readonly knowledge_base_id: string;
  readonly title?: string;
}): Promise<ConversationSummary> =>
  apiRequest("/ai/chat/conversations", {
    body: JSON.stringify(payload),
    method: "POST",
  });

export const getConversation = (id: string, signal?: AbortSignal) =>
  apiRequest<ConversationSummary>(`/ai/chat/conversations/${encodeURIComponent(id)}`, {
    signal,
  });

export function listConversationMessages(
  conversationId: string,
  options: {
    readonly limit?: number;
    readonly offset?: number;
    readonly signal?: AbortSignal;
  } = {},
): Promise<ChatMessagePage> {
  return apiRequest(
    `/ai/chat/conversations/${encodeURIComponent(conversationId)}/messages${pageQuery(options.limit ?? 100, options.offset ?? 0)}`,
    { signal: options.signal },
  );
}

export async function listLatestConversationMessages(
  conversationId: string,
  options: {
    readonly limit?: number;
    readonly signal?: AbortSignal;
  } = {},
): Promise<ChatMessagePage> {
  const limit = options.limit ?? 100;
  const summary = await listConversationMessages(conversationId, {
    limit: 1,
    offset: 0,
    signal: options.signal,
  });
  if (summary.total <= 1) {
    return { ...summary, limit, offset: 0 };
  }
  let total = summary.total;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const offset = Math.floor((total - 1) / limit) * limit;
    const page = await listConversationMessages(conversationId, {
      limit,
      offset,
      signal: options.signal,
    });
    const actualLatestOffset =
      page.total === 0 ? 0 : Math.floor((page.total - 1) / limit) * limit;
    if (page.offset === actualLatestOffset) return page;
    total = page.total;
  }
  throw new Error("Conversation history changed too quickly to load its latest page.");
}

export const submitChatMessage = (
  conversationId: string,
  content: string,
  idempotencyKey: string,
): Promise<ChatMessageSubmission> =>
  apiRequest(`/ai/chat/conversations/${encodeURIComponent(conversationId)}/messages`, {
    body: JSON.stringify({ content, idempotency_key: idempotencyKey }),
    method: "POST",
  });

export const archiveConversation = (
  conversationId: string,
): Promise<ConversationSummary> =>
  apiRequest(`/ai/chat/conversations/${encodeURIComponent(conversationId)}/archive`, {
    method: "POST",
  });

export const cancelChatMessage = (messageId: string): Promise<ChatMessage> =>
  apiRequest(`/ai/chat/messages/${encodeURIComponent(messageId)}/cancel`, {
    method: "POST",
  });
