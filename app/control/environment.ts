export function controlRouteAvailable(vercel: string | undefined) {
  return vercel !== "1";
}

export function resolveApiUrl(environment: string | undefined, configured: string | undefined) {
  if (environment !== "development" || !configured) return "";

  try {
    const url = new URL(configured);
    if (!["http:", "https:"].includes(url.protocol)) return "";
    if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)) return "";
    return url.origin;
  } catch {
    return "";
  }
}
