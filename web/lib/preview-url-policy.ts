import { lookup } from "node:dns/promises"
import { isIP } from "node:net"

export interface ResolvedAddress {
  address: string
  family?: number
}

export type AddressResolver = (
  hostname: string
) => Promise<readonly ResolvedAddress[]>

export interface PreviewTarget {
  url: URL
  address: string
  family: 4 | 6
}

export class UnsafePreviewUrlError extends Error {
  constructor(message: string) {
    super(message)
    this.name = "UnsafePreviewUrlError"
  }
}

export const MAX_PREVIEW_IMAGE_URL_LENGTH = 4096

export function resolvePreviewImageUrl(
  rawImage: string | null,
  pageUrl: URL
): string | null {
  if (!rawImage || rawImage.length > MAX_PREVIEW_IMAGE_URL_LENGTH) return null

  try {
    const imageUrl = new URL(rawImage, pageUrl)
    if (
      imageUrl.protocol !== "https:" ||
      imageUrl.href.length > MAX_PREVIEW_IMAGE_URL_LENGTH
    ) {
      return null
    }
    return imageUrl.href
  } catch {
    return null
  }
}

const defaultResolver: AddressResolver = (hostname) =>
  lookup(hostname, { all: true, verbatim: true })

function ipv4ToNumber(address: string): number | null {
  if (isIP(address) !== 4) return null

  return address
    .split(".")
    .map(Number)
    .reduce((value, octet) => (value * 256 + octet) >>> 0, 0)
}

function isInIpv4Range(address: number, network: string, prefix: number) {
  const networkValue = ipv4ToNumber(network)
  if (networkValue === null) return false
  const mask = prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0
  return (address & mask) === (networkValue & mask)
}

const BLOCKED_IPV4_RANGES: readonly [string, number][] = [
  ["0.0.0.0", 8],
  ["10.0.0.0", 8],
  ["100.64.0.0", 10],
  ["127.0.0.0", 8],
  ["169.254.0.0", 16],
  ["172.16.0.0", 12],
  ["192.0.0.0", 24],
  ["192.0.2.0", 24],
  ["192.88.99.0", 24],
  ["192.168.0.0", 16],
  ["198.18.0.0", 15],
  ["198.51.100.0", 24],
  ["203.0.113.0", 24],
  ["224.0.0.0", 4],
  ["240.0.0.0", 4],
]

function ipv6ToGroups(address: string): number[] | null {
  if (isIP(address) !== 6) return null

  const halves = address.toLowerCase().split("::")
  if (halves.length > 2) return null

  const parseHalf = (half: string): number[] => {
    if (!half) return []
    const groups = half.split(":")
    const last = groups.at(-1)
    if (last && isIP(last) === 4) {
      const ipv4 = ipv4ToNumber(last)
      if (ipv4 === null) return []
      groups.splice(
        -1,
        1,
        ((ipv4 >>> 16) & 0xffff).toString(16),
        (ipv4 & 0xffff).toString(16)
      )
    }
    return groups.map((group) => Number.parseInt(group, 16))
  }

  const left = parseHalf(halves[0])
  const right = parseHalf(halves[1] ?? "")
  const omitted = 8 - left.length - right.length
  if (omitted < 0 || (halves.length === 1 && omitted !== 0)) return null

  const groups = [...left, ...Array(omitted).fill(0), ...right]
  if (groups.length !== 8 || groups.some((group) => !Number.isFinite(group))) {
    return null
  }

  return groups
}

function isInIpv6Range(address: number[], network: string, prefix: number) {
  const networkGroups = ipv6ToGroups(network)
  if (networkGroups === null) return false

  const fullGroups = Math.floor(prefix / 16)
  for (let index = 0; index < fullGroups; index++) {
    if (address[index] !== networkGroups[index]) return false
  }

  const remainingBits = prefix % 16
  if (remainingBits === 0) return true
  const mask = (0xffff << (16 - remainingBits)) & 0xffff
  return (address[fullGroups] & mask) === (networkGroups[fullGroups] & mask)
}

const BLOCKED_IPV6_RANGES: readonly [string, number][] = [
  ["::", 96],
  ["64:ff9b::", 96],
  ["64:ff9b:1::", 48],
  ["100::", 64],
  ["2001::", 23],
  ["2001:db8::", 32],
  ["2002::", 16],
  ["3fff::", 20],
  ["5f00::", 16],
  ["fc00::", 7],
  ["fe80::", 10],
  ["fec0::", 10],
  ["ff00::", 8],
]

export function isPublicAddress(address: string): boolean {
  const version = isIP(address)
  if (version === 4) {
    const numericAddress = ipv4ToNumber(address)
    return (
      numericAddress !== null &&
      !BLOCKED_IPV4_RANGES.some(([network, prefix]) =>
        isInIpv4Range(numericAddress, network, prefix)
      )
    )
  }

  if (version === 6) {
    const addressGroups = ipv6ToGroups(address)
    if (addressGroups === null) return false

    const isGlobalUnicast = isInIpv6Range(addressGroups, "2000::", 3)
    return (
      isGlobalUnicast &&
      !BLOCKED_IPV6_RANGES.some(([network, prefix]) =>
        isInIpv6Range(addressGroups, network, prefix)
      )
    )
  }

  return false
}

export async function resolvePreviewTarget(
  rawUrl: string,
  resolveAddresses: AddressResolver = defaultResolver
): Promise<PreviewTarget> {
  let url: URL
  try {
    url = new URL(rawUrl)
  } catch {
    throw new UnsafePreviewUrlError("Invalid URL")
  }

  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new UnsafePreviewUrlError("Unsupported URL protocol")
  }
  if (url.username || url.password) {
    throw new UnsafePreviewUrlError("URL credentials are not allowed")
  }

  const hostname = url.hostname.replace(/^\[|\]$/g, "").replace(/\.$/, "")
  if (!hostname || hostname === "localhost" || hostname.endsWith(".localhost")) {
    throw new UnsafePreviewUrlError("Local hostnames are not allowed")
  }

  const addressVersion = isIP(hostname)
  if (addressVersion !== 0) {
    if (!isPublicAddress(hostname)) {
      throw new UnsafePreviewUrlError("Private or reserved addresses are not allowed")
    }
    return { url, address: hostname, family: addressVersion as 4 | 6 }
  }

  let addresses: readonly ResolvedAddress[]
  try {
    addresses = await resolveAddresses(hostname)
  } catch {
    throw new UnsafePreviewUrlError("Hostname could not be resolved")
  }

  if (
    addresses.length === 0 ||
    addresses.some(({ address }) => !isPublicAddress(address))
  ) {
    throw new UnsafePreviewUrlError("Hostname resolved to a private or reserved address")
  }

  const selected =
    addresses.find(({ address }) => isIP(address) === 4) ?? addresses[0]
  const family = isIP(selected.address)
  if (family !== 4 && family !== 6) {
    throw new UnsafePreviewUrlError("Hostname returned an invalid address")
  }

  return { url, address: selected.address, family }
}

export async function validatePreviewUrl(
  rawUrl: string,
  resolveAddresses: AddressResolver = defaultResolver
): Promise<URL> {
  return (await resolvePreviewTarget(rawUrl, resolveAddresses)).url
}
