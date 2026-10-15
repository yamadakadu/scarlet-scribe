import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { endOfLocalDay, startOfLocalDay } from '../lib/dates.ts'
import { api, unwrap, type MergeRequestState, type TaskOrder } from './client.ts'

export interface TaskFilters {
  q?: string
  status?: string
  assigneeId?: string
  containerId?: string
  /** Dias locais, AAAA-MM-DD. */
  dueFrom?: string
  dueTo?: string
  includeClosed?: boolean
  archived?: boolean
  orderBy?: TaskOrder
  limit: number
  offset: number
}

export function useTasks(f: TaskFilters) {
  return useQuery({
    queryKey: ['tasks', f],
    placeholderData: keepPreviousData,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/tasks', {
          params: {
            query: {
              q: f.q || undefined,
              status: f.status ? [f.status] : undefined,
              assignee_id: f.assigneeId,
              container_id: f.containerId,
              due_from: f.dueFrom ? startOfLocalDay(f.dueFrom) : undefined,
              due_to: f.dueTo ? endOfLocalDay(f.dueTo) : undefined,
              include_closed: f.includeClosed,
              archived: f.archived,
              order_by: f.orderBy,
              limit: f.limit,
              offset: f.offset,
            },
          },
        }),
      ),
  })
}

export function useTask(id: string) {
  return useQuery({
    queryKey: ['task', id],
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/tasks/{task_id}', { params: { path: { task_id: id } } })),
  })
}

export function useMilestones(
  containerId: string | undefined,
  dueFrom: string | undefined,
  dueTo: string | undefined,
) {
  return useQuery({
    queryKey: ['milestones', containerId, dueFrom, dueTo],
    placeholderData: keepPreviousData,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/milestones', {
          params: {
            query: { container_id: containerId, due_from: dueFrom, due_to: dueTo, limit: 200 },
          },
        }),
      ),
  })
}

export function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: async () => unwrap(await api.GET('/api/v1/projects')),
  })
}

export function usePeople() {
  return useQuery({
    queryKey: ['people'],
    queryFn: async () => unwrap(await api.GET('/api/v1/people', { params: { query: { limit: 200 } } })),
  })
}

export function useSources() {
  return useQuery({
    queryKey: ['sources'],
    staleTime: 30_000,
    queryFn: async () => unwrap(await api.GET('/api/v1/sources')),
  })
}

export function useRepositories(archived: boolean, limit = 200, offset = 0) {
  return useQuery({
    queryKey: ['repositories', archived, limit, offset],
    placeholderData: keepPreviousData,
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/repositories', { params: { query: { archived, limit, offset } } })),
  })
}

export interface MergeRequestFilters {
  repositoryId?: string
  state?: MergeRequestState
  q?: string
  limit: number
  offset: number
}

export function useMergeRequests(f: MergeRequestFilters) {
  return useQuery({
    queryKey: ['merge-requests', f],
    placeholderData: keepPreviousData,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/merge-requests', {
          params: {
            query: {
              repository_id: f.repositoryId,
              state: f.state ? [f.state] : undefined,
              q: f.q || undefined,
              limit: f.limit,
              offset: f.offset,
            },
          },
        }),
      ),
  })
}

export interface CommitFilters {
  repositoryId?: string
  /** Dias locais, AAAA-MM-DD. */
  from?: string
  to?: string
  q?: string
  limit: number
  offset: number
}

export function useCommits(f: CommitFilters) {
  return useQuery({
    queryKey: ['commits', f],
    placeholderData: keepPreviousData,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/commits', {
          params: {
            query: {
              repository_id: f.repositoryId,
              from: f.from ? startOfLocalDay(f.from) : undefined,
              to: f.to ? endOfLocalDay(f.to) : undefined,
              q: f.q || undefined,
              limit: f.limit,
              offset: f.offset,
            },
          },
        }),
      ),
  })
}
