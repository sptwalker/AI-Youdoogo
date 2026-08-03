// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchAttachmentBlob } from './discussion'
import { fetchDesktopAttachment, type Attachment } from './desktop'
import { TOKEN_KEY } from './http'

const attachment: Attachment = {
  type: 'file',
  name: 'brief.pdf',
  storage_path: 'uploads/brief.pdf',
  size: 128,
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
  sessionStorage.clear()
})

describe('attachment authentication', () => {
  it('uses the session-scoped token for discussion attachments', async () => {
    sessionStorage.setItem(TOKEN_KEY, 'session-token')
    const fetchMock = vi.fn().mockResolvedValue(new Response('discussion-file', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchAttachmentBlob(attachment)).resolves.toBeInstanceOf(Blob)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/channels/attachments/download?storage_path=uploads%2Fbrief.pdf&name=brief.pdf',
      expect.objectContaining({
        headers: { Authorization: 'Bearer session-token' },
      }),
    )
  })

  it('uses the session-scoped token for desktop attachments', async () => {
    sessionStorage.setItem(TOKEN_KEY, 'session-token')
    const fetchMock = vi.fn().mockResolvedValue(new Response('desktop-file', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchDesktopAttachment(attachment)).resolves.toBeInstanceOf(Blob)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/desktop/chat/attachments/download?storage_path=uploads%2Fbrief.pdf&name=brief.pdf',
      expect.objectContaining({
        headers: { Authorization: 'Bearer session-token' },
      }),
    )
  })
})
