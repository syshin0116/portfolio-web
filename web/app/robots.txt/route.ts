export function GET() {
  const body = `User-agent: *
Allow: /
Disallow: /login
Disallow: /api/

Sitemap: https://syshin0116.vercel.app/sitemap.xml

# Content Signals (https://contentsignals.org/)
Content-Signal: ai-train=disallow, search=allow, ai-input=allow
`;

  return new Response(body, {
    headers: { "Content-Type": "text/plain" },
  });
}
