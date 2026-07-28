// SERVER ONLY — reads Gemini API keys which must never reach the browser.
//
// Multi-key pool with round-robin (LRU) selection, per-key cooldown tracking,
// and automatic rotation on 429 / 5xx / network errors.
//
// Usage — stateless calls (text generation, embeddings):
//   import { geminiPool } from './pool'
//   const result = await geminiPool.call(ai => ai.models.generateContent({...}))
//
// Usage — Files-API sessions (upload → generate → delete):
//   The entire sequence MUST be in one call() so the same key is used throughout.
//   Gemini files are scoped to the key that uploaded them.
//   const result = await geminiPool.call(async ai => {
//     const file = await ai.files.upload({...})
//     try {
//       return await ai.models.generateContent({...})
//     } finally {
//       ai.files.delete({ name: file.name }).catch(() => {})
//     }
//   })
//
// Key sources (checked in order, de-duplicated):
//   1. GEMINI_API_KEYS=key1,key2,key3   (comma-separated)
//   2. GEMINI_API_KEY_1, GEMINI_API_KEY_2, ... GEMINI_API_KEY_20
//   3. GEMINI_API_KEY  (legacy single key — still works)
//
// Tunables (all optional, have sane defaults):
//   GEMINI_DEFAULT_COOLDOWN_MS  default 60000
//   GEMINI_BASE_BACKOFF_MS      default 500
//   GEMINI_MAX_BACKOFF_MS       default 8000
//   GEMINI_MAX_ATTEMPTS         default 0 (= min(keys*2, 16))
//   GEMINI_MAX_COOLDOWN_WAIT_MS default 30000 (fast-fail if cooldown > this)
//
// Error classification nuance:
//   401             → 'invalid-key'  → permanent disable (key is definitively rejected)
//   403/PERMISSION  → 'forbidden'    → 15-min cooldown (may be transient; NOT permanent)
//   429/EXHAUSTED   → 'rate-limit'   → short cooldown from Retry-After header

import { GoogleGenAI } from '@google/genai'
import { PipelineError } from './errors'
import { logger } from '@/lib/logger'

// ---------------------------------------------------------------------------
// Exported error type
// ---------------------------------------------------------------------------

export class AllGeminiKeysExhaustedError extends PipelineError {
  constructor(keyCount: number, attempts: number) {
    super(
      `All ${keyCount} Gemini key(s) exhausted after ${attempts} attempt(s). ` +
        `Check key validity and quota. The meeting will be marked failed and can be re-run.`,
    )
    this.name = 'AllGeminiKeysExhaustedError'
  }
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

interface PoolConfig {
  defaultCooldownMs: number
  baseBackoffMs: number
  maxBackoffMs: number
  /** 0 = auto: min(keys.length * 2, 16) */
  maxAttempts: number
  /** Don't block an HTTP request longer than this waiting for key cooldowns. Fast-fail if exceeded. */
  maxCooldownWaitMs: number
}

function readConfig(): PoolConfig {
  const n = (key: string, fallback: number) =>
    parseInt(process.env[key] ?? '', 10) || fallback
  return {
    defaultCooldownMs: n('GEMINI_DEFAULT_COOLDOWN_MS', 60_000),
    baseBackoffMs:     n('GEMINI_BASE_BACKOFF_MS', 500),
    maxBackoffMs:      n('GEMINI_MAX_BACKOFF_MS', 8_000),
    maxAttempts:       n('GEMINI_MAX_ATTEMPTS', 0),
    maxCooldownWaitMs: n('GEMINI_MAX_COOLDOWN_WAIT_MS', 30_000),
  }
}

// ---------------------------------------------------------------------------
// Per-key state
// ---------------------------------------------------------------------------

interface KeyState {
  readonly key: string
  /** DB id of this key (null for env-var fallback keys). Passed to logUsage. */
  readonly keyId: string | null
  /** 1-based; used in log messages only — never log the raw key value. */
  readonly index: number
  /** Epoch ms after which this key can be used again. 0 = no cooldown. */
  cooldownUntil: number
  /** Epoch ms of last use (0 = never used). Drives LRU selection. */
  lastUsedAt: number
  consecutiveFailures: number
  /** 401/403 → permanently skip for this process lifetime. */
  disabled: boolean
}

// ---------------------------------------------------------------------------
// Error classification
// ---------------------------------------------------------------------------

type ErrorClass = 'rate-limit' | 'invalid-key' | 'forbidden' | 'bad-request' | 'transient' | 'unknown'

function classifyError(err: unknown): ErrorClass {
  // PipelineError = our own validation / parse failure — surface immediately.
  if (err instanceof PipelineError) return 'bad-request'

  const msg = err instanceof Error ? err.message : String(err)

  if (/\b429\b/.test(msg) || /RESOURCE_EXHAUSTED/i.test(msg) || /quota/i.test(msg)) {
    return 'rate-limit'
  }
  // 401 definitively means the key is rejected → permanent disable.
  if (/\b401\b/.test(msg) || /API_KEY_INVALID/i.test(msg) || /invalid.api.key/i.test(msg)) {
    return 'invalid-key'
  }
  // 403 / PERMISSION_DENIED can be transient (model access, region restriction, project-level
  // quota, billing state) → long cooldown rather than permanent disable.
  if (/\b403\b/.test(msg) || /permission.denied/i.test(msg)) {
    return 'forbidden'
  }
  if (/\b400\b/.test(msg)) {
    return 'bad-request'
  }
  if (
    /\b(500|502|503|504)\b/.test(msg) ||
    /UNAVAILABLE/i.test(msg) ||
    /INTERNAL/i.test(msg) ||
    /ECONNRESET/i.test(msg) ||
    /ETIMEDOUT/i.test(msg) ||
    /fetch failed/i.test(msg) ||
    /network/i.test(msg)
  ) {
    return 'transient'
  }
  return 'unknown'
}

/** Extract a Retry-After duration in ms from the error message, if present. */
function parseRetryAfterMs(err: unknown): number | null {
  const msg = err instanceof Error ? err.message : String(err)
  // Matches: "retryDelay: 30s", "retry after 30", "Retry-After: 30"
  const m = msg.match(/retry[_\-\s]?(?:after|delay)[:\s=]+(\d+)/i)
  if (m) {
    const s = parseInt(m[1], 10)
    if (!isNaN(s) && s > 0) return s * 1_000
  }
  return null
}

function maskKey(key: string): string {
  return key.length >= 8 ? `...${key.slice(-4)}` : '...????'
}

function jitteredDelay(base: number, attempt: number, cap: number): number {
  const exp = Math.min(base * 2 ** attempt, cap)
  return exp * (0.75 + Math.random() * 0.5) // ±25% jitter
}

// ---------------------------------------------------------------------------
// Pool class
// ---------------------------------------------------------------------------

class GeminiKeyPool {
  private readonly keys: KeyState[]
  private readonly cfg: PoolConfig

  constructor(keys: Array<{ id: string | null; key: string }>, cfg: PoolConfig) {
    if (keys.length === 0) {
      throw new Error(
        'No Gemini API keys configured. ' +
          'Set GEMINI_API_KEYS (comma-separated) or GEMINI_API_KEY in .env.local.',
      )
    }
    this.keys = keys.map((k, i) => ({
      key: k.key,
      keyId: k.id,
      index: i + 1,
      cooldownUntil: 0,
      lastUsedAt: 0,
      consecutiveFailures: 0,
      disabled: false,
    }))
    this.cfg = cfg
    logger.info(`[gemini pool] initialised with ${keys.length} key(s)`, { count: keys.length })
  }

  /** Least-recently-used key that is neither cooling down nor disabled. */
  private nextKey(): KeyState | null {
    const now = Date.now()
    const healthy = this.keys.filter(k => !k.disabled && k.cooldownUntil <= now)
    if (healthy.length === 0) return null
    return healthy.reduce((best, k) => (k.lastUsedAt < best.lastUsedAt ? k : best))
  }

  /** Epoch ms when the next cooldown expires, or null if all keys are disabled. */
  private soonestCooldownMs(): number | null {
    const cooling = this.keys.filter(k => !k.disabled && k.cooldownUntil > Date.now())
    if (cooling.length === 0) return null
    return Math.min(...cooling.map(k => k.cooldownUntil))
  }

  /**
   * Execute `fn` with a healthy GoogleGenAI client.
   * `fn` receives the client and the DB id of the key used (null for env-var keys).
   * Existing callers that only use the first parameter continue to work unchanged.
   *
   * On retryable errors the pool puts the used key on cooldown (or disables it),
   * picks the next healthy key via LRU, and retries `fn` from scratch.
   *
   * For Files-API sessions the entire upload+generate+delete sequence should be
   * inside a single call() so the same key is used throughout (Gemini files are
   * scoped to the uploading key).
   */
  async call<T>(fn: (ai: GoogleGenAI, keyId: string | null) => Promise<T>): Promise<T> {
    const maxAttempts =
      this.cfg.maxAttempts > 0
        ? this.cfg.maxAttempts
        : Math.min(this.keys.length * 2, 16)

    let lastErr: unknown

    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      const keyState = this.nextKey()

      if (!keyState) {
        // All keys are either cooling down or permanently disabled.
        const nextMs = this.soonestCooldownMs()
        if (nextMs === null) {
          // Every key is permanently disabled — no recovery possible.
          throw new AllGeminiKeysExhaustedError(this.keys.length, attempt)
        }
        const waitMs = Math.max(0, nextMs - Date.now()) + 50
        if (waitMs > this.cfg.maxCooldownWaitMs) {
          // Cooldown wait exceeds the per-request threshold — fast-fail rather than
          // blocking the HTTP request. The key will become available again once the
          // cooldown expires; the next incoming request can use it.
          logger.warn(
            `[gemini pool] all keys on cooldown for ${Math.round(waitMs / 1_000)}s; exceeds maxCooldownWaitMs — failing fast`,
          )
          throw new AllGeminiKeysExhaustedError(this.keys.length, attempt)
        }
        logger.warn(
          `[gemini pool] all keys on cooldown; waiting ${Math.round(waitMs / 1_000)}s for next available key`,
          { count: attempt + 1 },
        )
        await new Promise(r => setTimeout(r, waitMs))
        // Don't consume an attempt slot for a pure cooldown wait.
        attempt--
        continue
      }

      keyState.lastUsedAt = Date.now()
      const ai = new GoogleGenAI({ apiKey: keyState.key })

      try {
        const result = await fn(ai, keyState.keyId)
        keyState.consecutiveFailures = 0
        return result
      } catch (err) {
        lastErr = err
        const errClass = classifyError(err)

        if (errClass === 'bad-request') {
          throw err // our bug or non-recoverable — surface immediately
        }

        const snippet = (err instanceof Error ? err.message : String(err)).slice(0, 120)

        if (errClass === 'rate-limit') {
          const cooldownMs = parseRetryAfterMs(err) ?? this.cfg.defaultCooldownMs
          keyState.cooldownUntil = Date.now() + cooldownMs
          keyState.consecutiveFailures++
          logger.warn(
            `[gemini pool] key #${keyState.index} rate-limited; cooldown ${Math.round(cooldownMs / 1_000)}s — rotating`,
            { count: attempt + 1 },
          )
        } else if (errClass === 'invalid-key') {
          keyState.disabled = true
          logger.warn(`[gemini pool] key #${keyState.index} rejected with 401 — permanently disabled; rotating`)
        } else if (errClass === 'forbidden') {
          // 403 / PERMISSION_DENIED: apply a long cooldown instead of permanent disable.
          // This lets the key recover if the condition was transient (model restriction,
          // region issue, temporary project limitation). If it persists, every cooldown
          // expiry will retry once and cool down again — visible in warn logs.
          const cooldownMs = 15 * 60 * 1_000
          keyState.cooldownUntil = Date.now() + cooldownMs
          keyState.consecutiveFailures++
          logger.warn(
            `[gemini pool] key #${keyState.index} got 403/PERMISSION_DENIED; applying 15-min cooldown`,
            { count: attempt + 1 },
          )
        } else {
          // transient or unknown — try the next key without a cooldown
          keyState.consecutiveFailures++
          logger.warn(
            `[gemini pool] key #${keyState.index} transient error`,
            { count: attempt + 1, detail: snippet },
          )
        }

        if (attempt < maxAttempts - 1) {
          const delay = jitteredDelay(this.cfg.baseBackoffMs, attempt, this.cfg.maxBackoffMs)
          await new Promise(r => setTimeout(r, delay))
        }
      }
    }

    throw new AllGeminiKeysExhaustedError(this.keys.length, maxAttempts)
  }
}

// ---------------------------------------------------------------------------
// Key loading — async, reads DB keys via provider (with env-var fallback).
// ---------------------------------------------------------------------------

import { getActiveKeysWithMeta } from '../keys/provider'

// ---------------------------------------------------------------------------
// Pool singleton with TTL-based refresh.
//
// The pool is re-created every POOL_TTL_MS (30 s) so newly added or disabled
// DB keys take effect without a process restart. Per-key cooldown state is
// intentionally lost on refresh — cooldowns naturally expire within the TTL.
//
// resetGeminiPool() forces an immediate refresh (call after key mutations).
// ---------------------------------------------------------------------------

const POOL_TTL_MS = 30_000

let _pool:         GeminiKeyPool | null = null
let _poolLoadedAt  = 0

/** Force the pool to reload keys on the next call (used after key mutations). */
export function resetGeminiPool(): void {
  _pool = null
  _poolLoadedAt = 0
}

async function getPoolAsync(): Promise<GeminiKeyPool> {
  const now = Date.now()
  if (!_pool || now - _poolLoadedAt > POOL_TTL_MS) {
    const keys = await getActiveKeysWithMeta('gemini')
    _pool = new GeminiKeyPool(keys, readConfig())
    _poolLoadedAt = now
  }
  return _pool
}

export const geminiPool = {
  async call<T>(fn: (ai: GoogleGenAI, keyId: string | null) => Promise<T>): Promise<T> {
    const pool = await getPoolAsync()
    return pool.call(fn)
  },
}
