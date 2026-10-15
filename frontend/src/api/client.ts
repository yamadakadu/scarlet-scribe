import createClient from 'openapi-fetch'
import type { components, paths } from './schema.gen.ts'

// Os caminhos do OpenAPI já levam o prefixo /api/v1.
export const api = createClient<paths>({ baseUrl: '' })

export type Task = components['schemas']['TaskOut']
export type TaskDetail = components['schemas']['TaskDetail']
export type ProjectNode = components['schemas']['ProjectNode']
export type Person = components['schemas']['PersonOut']
export type SyncRun = components['schemas']['SyncRunOut']
export type Repository = components['schemas']['RepositoryOut']
export type MergeRequest = components['schemas']['MergeRequestOut']
export type Commit = components['schemas']['CommitOut']
export type Source = components['schemas']['SourceOut']
export type MergeRequestState = components['schemas']['MergeRequestState']
export type TaskOrder = components['schemas']['TaskOrder']

export class ApiError extends Error {
  status: number
  retryAfter: number | null

  constructor(status: number, message: string, retryAfter: number | null = null) {
    super(message)
    this.status = status
    this.retryAfter = retryAfter
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response }

/** Devolve `data` ou lança ApiError com o `detail` da API (ou do HTTP). */
export function unwrap<T>({ data, error, response }: Result<T>): T {
  if (response.ok && data !== undefined) return data
  const detail =
    typeof error === 'object' && error !== null && 'detail' in error
      ? String((error as { detail: unknown }).detail)
      : `Erro ${response.status}`
  const retry = Number(response.headers.get('Retry-After'))
  throw new ApiError(response.status, detail, Number.isFinite(retry) && retry > 0 ? retry : null)
}
