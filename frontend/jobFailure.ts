import { isLocal } from './access'
import type { JobStatus } from './types'

/** A job that failed on the local server costs nothing to send again. */
export function jobIsFree(job: Pick<JobStatus, 'errorParams'>) {
  return isLocal(String(job.errorParams?.provider || ''))
}

// Old jobs may carry only the provider's unstructured error.
export function jobFailureAdvice(job: Pick<JobStatus, 'error' | 'errorParams'>) {
  const message = [job.error, job.errorParams?.detail].filter(Boolean).join(' ')
  if (/imagine:content-moderated|generated image rejected by content moderation/i.test(message)) return 'job.moderated'
  // That advice warns about a new charge, which the local server never makes.
  if (!jobIsFree(job) && /(?:returned HTTP|failed \()\s*(?:500|502|503|504)\b/i.test(message)) return 'job.temporaryProviderError'
  return undefined
}
