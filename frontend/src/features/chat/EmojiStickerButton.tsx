/** 聊天输入框的表情入口：系统 emoji + 本地导入的 QQ 表情包。
 *  emoji 追加到文本；表情包点一下即作为图片附件走既有上传管线。
 *  variant 控制入口形态：both=一个按钮内含两页签；emoji/sticker=拆成单独工具栏按钮。 */
import { PictureOutlined, SmileOutlined } from '@ant-design/icons'
import { Button, Empty, Popover, Tabs, Upload, message, type ButtonProps } from 'antd'
import { useEffect, useState } from 'react'
import { COMMON_EMOJIS } from './emoji'
import { deleteSticker, importStickers, listStickers, type StoredSticker } from './stickerStore'

interface StickerView extends StoredSticker {
  url: string
}

export interface EmojiStickerButtonProps {
  /** 插入 emoji 字符（追加到输入框文本末尾）。 */
  onInsertEmoji(char: string): void
  /** 选中一张表情包 → 作为图片附件上传（复用输入框既有 upload 处理）。 */
  onPickSticker(file: File): Promise<boolean> | void
  disabled?: boolean
  variant?: 'both' | 'emoji' | 'sticker'
  type?: ButtonProps['type']
}

export function EmojiStickerButton({
  onInsertEmoji,
  onPickSticker,
  disabled,
  variant = 'both',
  type,
}: EmojiStickerButtonProps) {
  const [open, setOpen] = useState(false)
  const [stickers, setStickers] = useState<StickerView[]>([])
  const needStickers = variant !== 'emoji'

  useEffect(() => {
    if (!needStickers) return
    let revoked = false
    const created: string[] = []
    void listStickers().then((items) => {
      if (revoked) return
      setStickers(items.map((item) => {
        const url = URL.createObjectURL(item.blob)
        created.push(url)
        return { ...item, url }
      }))
    }).catch(() => { /* IndexedDB 不可用（隐私模式/测试环境）时忽略，表情包功能降级为空 */ })
    return () => {
      revoked = true
      created.forEach((url) => URL.revokeObjectURL(url))
    }
  }, [needStickers])

  const handleImport = async (files: File[]) => {
    let stored
    try {
      stored = await importStickers(files)
    } catch {
      message.error('表情包保存失败（浏览器存储不可用）')
      return
    }
    if (stored.length === 0) {
      message.warning('请选择图片文件（QQ 表情为 gif/png/jpg 图片）')
      return
    }
    setStickers((current) => [
      ...current,
      ...stored.map((item) => ({ ...item, url: URL.createObjectURL(item.blob) })),
    ])
    message.success(`已导入 ${stored.length} 个表情`)
  }

  const handleDelete = async (sticker: StickerView) => {
    await deleteSticker(sticker.id)
    URL.revokeObjectURL(sticker.url)
    setStickers((current) => current.filter((item) => item.id !== sticker.id))
  }

  const handlePick = (sticker: StickerView) => {
    void onPickSticker(new File([sticker.blob], sticker.name, { type: sticker.blob.type }))
    setOpen(false)
  }

  const emojiPanel = (
    <div style={{ maxHeight: 220, overflowY: 'auto', display: 'flex', flexWrap: 'wrap' }}>
      {COMMON_EMOJIS.map((emoji) => (
        <span
          key={emoji}
          onClick={() => onInsertEmoji(emoji)}
          style={{ cursor: 'pointer', fontSize: 22, padding: 4, lineHeight: 1, borderRadius: 4 }}
        >
          {emoji}
        </span>
      ))}
    </div>
  )

  const stickerPanel = (
    <div>
      <Upload
        accept="image/*"
        multiple
        showUploadList={false}
        beforeUpload={(_file, fileList) => {
          void handleImport(fileList as File[])
          return false
        }}
      >
        <Button size="small" type="dashed" block style={{ marginBottom: 8 }}>
          导入 QQ 表情包（选图片）
        </Button>
      </Upload>
      {stickers.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有表情包" />
      ) : (
        <div style={{ maxHeight: 200, overflowY: 'auto', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {stickers.map((sticker) => (
            <div
              key={sticker.id}
              title={sticker.name}
              onClick={() => handlePick(sticker)}
              style={{ position: 'relative', cursor: 'pointer' }}
            >
              <img
                src={sticker.url}
                alt={sticker.name}
                style={{ width: 56, height: 56, objectFit: 'cover', borderRadius: 6, border: '1px solid #f0f0f0' }}
              />
              <a
                onClick={(event) => { event.stopPropagation(); void handleDelete(sticker) }}
                style={{ position: 'absolute', top: -6, right: -6, background: '#fff', borderRadius: '50%', width: 16, height: 16, lineHeight: '14px', textAlign: 'center', fontSize: 12, color: '#cf1322', border: '1px solid #eee' }}
              >
                ×
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  )

  const content = variant === 'emoji'
    ? emojiPanel
    : variant === 'sticker'
      ? stickerPanel
      : (
        <Tabs
          size="small"
          items={[
            { key: 'emoji', label: '表情', children: emojiPanel },
            { key: 'sticker', label: '表情包', children: stickerPanel },
          ]}
        />
      )

  const icon = variant === 'sticker' ? <PictureOutlined /> : <SmileOutlined />
  const title = variant === 'sticker' ? '贴图 / 表情包' : variant === 'emoji' ? '表情' : '表情 / 表情包'

  return (
    <Popover content={<div style={{ width: 300 }}>{content}</div>} trigger="click" open={open} onOpenChange={setOpen} placement="topLeft">
      <Button type={type} icon={icon} disabled={disabled} title={title} />
    </Popover>
  )
}
