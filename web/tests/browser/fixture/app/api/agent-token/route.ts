const encode = (value: object) =>
  Buffer.from(JSON.stringify(value)).toString("base64url")

export async function POST() {
  const token = `${encode({ alg: "HS256", typ: "JWT" })}.${encode({
    exp: 4_102_444_800,
    sub: "browser-fixture-user",
  })}.fixture-signature`
  return Response.json({ token })
}
