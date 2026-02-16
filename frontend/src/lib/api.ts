import type { BuildResponse } from './types'

const BASE = import.meta.env.DEV ? '/api' : ''

export async function buildProject(prompt: string): Promise<BuildResponse> {
  const res = await fetch(`${BASE}/build`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt }),
  })
  if (!res.ok) throw new Error(`Build failed: ${res.statusText}`)
  return res.json()
}

export async function searchParts(query: string, limit = 20) {
  const res = await fetch(`${BASE}/search?q=${encodeURIComponent(query)}&limit=${limit}`)
  return res.json()
}

export async function getStats() {
  const res = await fetch(`${BASE}/stats`)
  return res.json()
}
