import { ImageResponse } from "next/og"

export const runtime = "edge"
export const alt = "Syshin0116 Dev"
export const size = { width: 1200, height: 630 }
export const contentType = "image/png"

export default async function OGImage() {
  const logoData = await fetch(
    new URL("/logo.png", "https://syshin0116.vercel.app")
  ).then((r) => r.arrayBuffer())
  const logoSrc = `data:image/png;base64,${Buffer.from(logoData).toString("base64")}`

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          backgroundColor: "#09090b",
          padding: "80px 100px",
          fontFamily: "sans-serif",
        }}
      >
        {/* Left: text */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "8px",
          }}
        >
          <div
            style={{
              fontSize: "88px",
              fontWeight: 800,
              color: "#ffffff",
              lineHeight: 1.1,
              letterSpacing: "-3px",
            }}
          >
            Syshin0116's
          </div>
          <div
            style={{
              fontSize: "88px",
              fontWeight: 800,
              color: "#a1a1aa",
              lineHeight: 1.1,
              letterSpacing: "-3px",
            }}
          >
            Dev
          </div>
        </div>

        {/* Right: logo */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={logoSrc}
          width={240}
          height={240}
          style={{ objectFit: "contain" }}
          alt="logo"
        />
      </div>
    ),
    { ...size }
  )
}
