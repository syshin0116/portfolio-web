export function getBlogSlug(pathname: string): string {
  const encodedSlug = pathname.replace(/^\/blog\/?/, "")

  try {
    return decodeURIComponent(encodedSlug)
  } catch {
    return encodedSlug
  }
}
