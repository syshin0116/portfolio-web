import { NextResponse } from "next/server"
import graphData from "@/.generated/graph.json"

export const dynamic = "force-static"

export async function GET() {
  return NextResponse.json(graphData)
}
