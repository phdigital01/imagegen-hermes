/** Hand text to the Hermes chat composer through the SDK, never the composer DOM. */
import { host } from '@hermes/plugin-sdk'

/** The composer's image attachment token: the chat shows it as a chip and the agent sees the image. */
export function imageRef(path: string): string {
  if (!/[\s()[\]{}<>"'`]/.test(path)) return `@image:${path}`
  return path.includes('`') ? `@image:"${path}"` : `@image:\`${path}\``
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Put `text` in the chat input for the user to review and send.
 * When ImageGen fills the window no composer is mounted, so the last chat
 * (or a new one) opens first and the write retries until it mounts.
 */
export async function writeToChat(text: string): Promise<boolean> {
  if (await host.composer.insertText(null, text, { mode: 'block' })) return true
  const stored = host.state.focusedStoredSessionId.get()
  if (stored) void host.openSession(stored)
  else host.newChat()
  for (let attempt = 0; attempt < 20; attempt++) {
    await wait(150)
    if (await host.composer.insertText(stored ? null : 'new', text, { mode: 'block' })) return true
  }
  return false
}
