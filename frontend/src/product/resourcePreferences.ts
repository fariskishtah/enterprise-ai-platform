export type FavoriteResourceType = "alert" | "factory" | "machine";

export interface ResourceShortcut {
  readonly id: string;
  readonly label: string;
  readonly path: string;
  readonly type: FavoriteResourceType;
}

const MAX_RECENT = 12;

function storageKey(userId: string, kind: "favorites" | "recent"): string {
  return `fk-${kind}:${userId}`;
}

function read(userId: string, kind: "favorites" | "recent"): ResourceShortcut[] {
  try {
    const parsed: unknown = JSON.parse(
      localStorage.getItem(storageKey(userId, kind)) ?? "[]",
    );
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is ResourceShortcut =>
        typeof item === "object" &&
        item !== null &&
        "id" in item &&
        typeof item.id === "string" &&
        "label" in item &&
        typeof item.label === "string" &&
        "path" in item &&
        typeof item.path === "string" &&
        item.path.startsWith("/") &&
        "type" in item &&
        ["alert", "factory", "machine"].includes(String(item.type)),
    );
  } catch {
    return [];
  }
}

function write(
  userId: string,
  kind: "favorites" | "recent",
  items: readonly ResourceShortcut[],
): void {
  localStorage.setItem(storageKey(userId, kind), JSON.stringify(items));
  window.dispatchEvent(new Event("fk-resource-shortcuts"));
}

export function readFavorites(userId: string): readonly ResourceShortcut[] {
  return read(userId, "favorites");
}

export function readRecentResources(userId: string): readonly ResourceShortcut[] {
  return read(userId, "recent");
}

export function recordRecentResource(userId: string, item: ResourceShortcut): void {
  const current = read(userId, "recent").filter(
    (candidate) => !(candidate.type === item.type && candidate.id === item.id),
  );
  write(userId, "recent", [item, ...current].slice(0, MAX_RECENT));
}

export function removeResourceShortcut(userId: string, item: ResourceShortcut): void {
  (["favorites", "recent"] as const).forEach((kind) => {
    write(
      userId,
      kind,
      read(userId, kind).filter(
        (candidate) => !(candidate.type === item.type && candidate.id === item.id),
      ),
    );
  });
}

export function toggleFavoriteResource(
  userId: string,
  item: ResourceShortcut,
): boolean {
  const current = read(userId, "favorites");
  const exists = current.some(
    (candidate) => candidate.type === item.type && candidate.id === item.id,
  );
  write(
    userId,
    "favorites",
    exists
      ? current.filter(
          (candidate) => !(candidate.type === item.type && candidate.id === item.id),
        )
      : [item, ...current].slice(0, MAX_RECENT),
  );
  return !exists;
}
