// 统一的后端调用封装：把契约 §1.4 的错误响应转换为可读异常。

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail: unknown

  constructor(message: string, status: number, code = 'HTTP_ERROR', detail: unknown = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }
}

interface ErrorBody {
  code?: string
  message?: string
  detail?: unknown
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (typeof init.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let resp: Response
  try {
    resp = await fetch(path, { ...init, headers })
  } catch {
    throw new ApiError('无法连接到服务，请检查网络后重试', 0, 'NETWORK_ERROR')
  }

  let body: unknown = null
  const text = await resp.text()
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = text
    }
  }

  if (!resp.ok) {
    const err = (body && typeof body === 'object' ? body : {}) as ErrorBody
    const fallback =
      resp.status >= 500 ? '服务暂时不可用，请稍后重试' : `HTTP ${resp.status}`
    const textBody = typeof body === 'string' ? body.trim() : ''
    const message =
      typeof err.message === 'string'
        ? err.message
        : textBody && textBody.length < 200 && !textBody.startsWith('<')
          ? textBody
          : fallback
    throw new ApiError(message, resp.status, err.code ?? 'HTTP_ERROR', err.detail ?? null)
  }

  return (body ?? null) as T
}

export const api = {
  get: <T>(path: string) => apiRequest<T>(path),
  post: <T>(path: string, body?: unknown) =>
    apiRequest<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  put: <T>(path: string, body?: unknown) =>
    apiRequest<T>(path, {
      method: 'PUT',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  del: <T = void>(path: string) => apiRequest<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, file: File, field = 'file') => {
    const form = new FormData()
    form.append(field, file)
    return apiRequest<T>(path, { method: 'POST', body: form })
  },
}

/** 路由不存在（后端尚未实现该接口）与“资源不存在”区分开。 */
export function isRouteMissing(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false
  if (error.status === 405 || error.status === 501) return true
  if (error.status === 404) {
    return error.code === 'NOT_IMPLEMENTED' || /^not found$/i.test(error.message.trim())
  }
  return false
}

export function errorMessage(error: unknown, fallback = '操作失败'): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return fallback
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(2)}s`
  return `${Math.floor(ms / 60_000)}m${Math.round((ms % 60_000) / 1000)}s`
}

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function relativeTime(value: string): string {
  const date = new Date(value).getTime()
  if (Number.isNaN(date)) return ''
  const diff = Date.now() - date
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)} 天前`
  return new Date(value).toLocaleDateString('zh-CN')
}
