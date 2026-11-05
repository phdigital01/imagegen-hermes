import type { JobStatus } from './types'

// Old jobs may carry only the provider's unstructured error.
export function jobFailureAdvice(job: Pick<JobStatus, 'error' | 'errorParams'>) {
  const message = [job.error, job.errorParams?.detail].filter(Boolean).join(' ')
  if (/imagine:content-moderated|generated image rejected by content moderation/i.test(message)) return 'job.moderated'
  if (/(?:returned HTTP|failed \()\s*(?:500|502|503|504)\b/i.test(message)) return 'job.temporaryProviderError'
  return undefined
}
