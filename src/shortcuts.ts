export interface ShortcutEvent {
  ctrlKey: boolean;
  metaKey: boolean;
  key: string;
}

export function isImportShortcut(event: ShortcutEvent): boolean {
  return (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "o";
}
