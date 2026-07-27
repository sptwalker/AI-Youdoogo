/** 浏览器截图：用屏幕捕获 API 抓取一帧为 PNG 图片，再走既有附件上传。
 *  ponytail: web 无法做原生「框选」截图，只能 getDisplayMedia 让用户选屏/窗口/标签页后抓整帧；
 *  需要框选精度时改用桌面端(Electron)原生截图接口。 */
export async function captureScreenshot(): Promise<File | null> {
  const media = navigator.mediaDevices
  if (!media?.getDisplayMedia) throw new Error('unsupported')

  const stream = await media.getDisplayMedia({ video: true })
  try {
    const video = document.createElement('video')
    video.srcObject = stream
    video.muted = true
    await new Promise<void>((resolve) => { video.onloadedmetadata = () => resolve() })
    await video.play()

    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(video, 0, 0)

    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
    if (!blob) return null
    return new File([blob], `screenshot-${Date.now()}.png`, { type: 'image/png' })
  } finally {
    stream.getTracks().forEach((track) => track.stop())
  }
}
