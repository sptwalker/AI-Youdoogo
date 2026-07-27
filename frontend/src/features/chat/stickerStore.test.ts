import { describe, expect, it } from 'vitest'
import { filterImageFiles } from './stickerStore'

/** 只放行图片：QQ 表情包是图片，误选的文档/文本要被丢弃。 */
describe('filterImageFiles', () => {
  it('keeps images and drops non-images', () => {
    const png = new File(['x'], 'a.png', { type: 'image/png' })
    const gif = new File(['x'], 'b.gif', { type: 'image/gif' })
    const txt = new File(['x'], 'c.txt', { type: 'text/plain' })
    const pdf = new File(['x'], 'd.pdf', { type: 'application/pdf' })

    const kept = filterImageFiles([png, gif, txt, pdf])

    expect(kept.map((file) => file.name)).toEqual(['a.png', 'b.gif'])
  })

  it('returns empty when nothing is an image', () => {
    const txt = new File(['x'], 'c.txt', { type: 'text/plain' })
    expect(filterImageFiles([txt])).toEqual([])
  })
})
