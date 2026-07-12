export function tagPath(tag: string): string {
  return tag.split("/").map(encodeURIComponent).join("/")
}
