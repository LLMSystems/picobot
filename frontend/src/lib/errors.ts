export class ApiError extends Error {
  code: string
  requestId?: string
  status?: number

  constructor(code: string, message: string, requestId?: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.requestId = requestId
    this.status = status
  }
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError'
}
