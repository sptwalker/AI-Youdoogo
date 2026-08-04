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

async function expectBlobPayload(blob: Blob, expectedText: string) {
  expect(Object.prototype.toString.call(blob)).toBe('[object Blob]')
  expect(blob.size).toBe(expectedText.length)
  expect(blob.type).toBe('text/plain;charset=utf-8')
  await expect(blob.text()).resolves.toBe(expectedText)
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

    await expectBlobPayload(await fetchAttachmentBlob(attachment), 'discussion-file')

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

    await expectBlobPayload(await fetchDesktopAttachment(attachment), 'desktop-file')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/desktop/chat/attachments/download?storage_path=uploads%2Fbrief.pdf&name=brief.pdf',
      expect.objectContaining({
        headers: { Authorization: 'Bearer session-token' },
      }),
    )
  })
})
