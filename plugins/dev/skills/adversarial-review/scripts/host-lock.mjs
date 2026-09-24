/**
 * Cross-process, per-host mutex for external-review.mjs: one lock file per
 * endpoint host:port, so every review process on this machine (any session,
 * any workflow) sends at most one request to a given model host at a time.
 *
 * The lock is a file created with O_EXCL holding {pid, host, token}. The holder
 * refreshes its mtime every heartbeat. A waiter breaks the lock when the holder
 * is gone: its pid is dead (checked only when the lock was written from this
 * hostname, since pids from another machine or container mean nothing here) or
 * its mtime is older than staleMs. Breaking is itself guarded by a short-lived
 * `.break` file so two waiters cannot both unlink and then delete each other's
 * fresh lock. Waiters poll with jitter; order is not FIFO.
 */

import { randomUUID } from 'node:crypto'
import { closeSync, mkdirSync, openSync, readFileSync, statSync, unlinkSync, utimesSync, writeSync } from 'node:fs'
import { homedir, hostname } from 'node:os'
import { join } from 'node:path'

const DEFAULT_STALE_MS = 120_000
const DEFAULT_POLL_MS = 500
// A break section lasts microseconds; one older than this was left by a crash.
const BREAK_STALE_MS = 10_000

export class LockWaitError extends Error {}

export function hostKey(baseUrl) {
  const u = new URL(baseUrl)
  const port = u.port || (u.protocol === 'https:' ? '443' : '80')
  return `${u.hostname.toLowerCase()}:${port}`
}

export function defaultLockDir(env) {
  if (env.EXTERNAL_REVIEW_LOCK_DIR) return env.EXTERNAL_REVIEW_LOCK_DIR
  return join(env.XDG_CACHE_HOME || join(homedir(), '.cache'), 'external-review')
}

export function lockPath(dir, key) {
  return join(dir, `${key.replace(/[^\w.-]/g, '_')}.lock`)
}

function tryCreate(path, content) {
  let fd
  try {
    fd = openSync(path, 'wx')
  } catch (e) {
    if (e.code === 'EEXIST') return false
    throw e
  }
  try {
    writeSync(fd, content)
  } finally {
    closeSync(fd)
  }
  return true
}

function pidAlive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch (e) {
    return e.code === 'EPERM'
  }
}

// Returns the lock's inode when it is stale, else null (fresh, or already gone).
// An empty or half-written file is a holder mid-create: judged by mtime only.
function staleInode(path, staleMs) {
  let st, holder
  try {
    st = statSync(path)
    holder = JSON.parse(readFileSync(path, 'utf8'))
  } catch (e) {
    if (e.code === 'ENOENT') return null
    holder = null
  }
  if (!st) return null
  const expired = Date.now() - st.mtimeMs > staleMs
  const orphaned = holder?.host === hostname() && Number.isInteger(holder.pid) && !pidAlive(holder.pid)
  return expired || orphaned ? st.ino : null
}

function unlinkQuiet(path) {
  try {
    unlinkSync(path)
  } catch (e) {
    if (e.code !== 'ENOENT') throw e
  }
}

// Removes the lock at `path` if it is stale. Returns true when it did.
function breakIfStale(path, staleMs) {
  if (staleInode(path, staleMs) === null) return false
  const guard = `${path}.break`
  if (!tryCreate(guard, String(process.pid))) {
    try {
      if (Date.now() - statSync(guard).mtimeMs > BREAK_STALE_MS) unlinkQuiet(guard)
    } catch (e) {
      if (e.code !== 'ENOENT') throw e
    }
    return false
  }
  try {
    // Re-check under the guard: another waiter may have broken and re-taken it.
    const ino = staleInode(path, staleMs)
    if (ino === null || statSync(path).ino !== ino) return false
    unlinkQuiet(path)
    return true
  } catch (e) {
    if (e.code === 'ENOENT') return true
    throw e
  } finally {
    unlinkQuiet(guard)
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Waits for the host lock, up to maxWaitMs.
 *
 * Args:
 *   key: hostKey() of the endpoint.
 *   opts: {dir, maxWaitMs, staleMs?, pollMs?}.
 *
 * Returns:
 *   {waitedMs, release}; release() is idempotent and also runs on process exit.
 *
 * Raises:
 *   LockWaitError: the host stayed busy past maxWaitMs.
 */
export async function acquireHostLock(key, { dir, maxWaitMs, staleMs = DEFAULT_STALE_MS, pollMs = DEFAULT_POLL_MS }) {
  mkdirSync(dir, { recursive: true })
  const path = lockPath(dir, key)
  const token = randomUUID()
  const content = JSON.stringify({ pid: process.pid, host: hostname(), token, key, acquiredAt: new Date().toISOString() })
  const started = Date.now()
  while (!tryCreate(path, content)) {
    if (breakIfStale(path, staleMs)) continue
    const waited = Date.now() - started
    if (waited >= maxWaitMs) {
      throw new LockWaitError(`queued past max wait: ${key} was busy with another review for ${Math.round(waited / 1000)}s (max wait ${maxWaitMs} ms, EXTERNAL_REVIEW_MAX_WAIT_MS)`)
    }
    await sleep(Math.min(pollMs * (0.5 + Math.random()), maxWaitMs - waited))
  }
  const waitedMs = Date.now() - started

  const heartbeat = setInterval(() => {
    try {
      const now = new Date()
      utimesSync(path, now, now)
    } catch {
      // Lock broken under us; release() still checks the token before unlinking.
    }
  }, Math.max(1_000, staleMs / 4))
  heartbeat.unref()

  let released = false
  const release = () => {
    if (released) return
    released = true
    clearInterval(heartbeat)
    process.off('exit', release)
    try {
      if (JSON.parse(readFileSync(path, 'utf8')).token === token) unlinkSync(path)
    } catch {
      // Already gone or taken over after a stale break: not ours to remove.
    }
  }
  process.on('exit', release)
  return { waitedMs, release }
}
