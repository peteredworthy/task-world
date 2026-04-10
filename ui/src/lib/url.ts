export function normalizeBaseUrl(url: string | null | undefined): string {
  return (url ?? '').trim().replace(/\/+$/, '');
}

export function joinBaseUrl(baseUrl: string, path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${normalizeBaseUrl(baseUrl)}${normalizedPath}`;
}

