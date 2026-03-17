export const API_BASE = import.meta.env.VITE_ARCHON_API_BASE || "http://localhost:8000";

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {})
    },
    ...options
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
}

export async function streamJsonLines(
  path: string,
  body: unknown,
  onLine: (payload: any) => void
): Promise<void> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/x-ndjson"
    },
    body: JSON.stringify(body)
  });

  if (!response.ok || !response.body) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n");
    while (boundary !== -1) {
      const line = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 1);
      if (line) {
        try {
          onLine(JSON.parse(line));
        } catch {
          onLine({ type: "error", payload: { message: "Malformed stream line." } });
        }
      }
      boundary = buffer.indexOf("\n");
    }
  }
}
