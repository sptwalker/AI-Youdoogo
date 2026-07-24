export class InvalidConfigValue extends Error {}

export function normalizeConfigValue(valueType: string, raw: unknown): unknown {
  if (valueType === 'bool') {
    if (typeof raw === 'boolean') return raw
    if (typeof raw === 'string') {
      const normalized = raw.trim().toLowerCase()
      if (normalized === 'true') return true
      if (normalized === 'false') return false
    }
    throw new InvalidConfigValue('布尔配置只能填写 true 或 false')
  }

  if (valueType === 'int') {
    const candidate = typeof raw === 'number'
      ? raw
      : typeof raw === 'string' && /^-?\d+$/.test(raw.trim())
        ? Number(raw.trim())
        : Number.NaN
    if (!Number.isSafeInteger(candidate)) {
      throw new InvalidConfigValue('整数配置必须是有效的安全整数')
    }
    return candidate
  }

  if (typeof raw !== 'string') {
    throw new InvalidConfigValue('文本配置必须是字符串')
  }
  return raw
}

export function configInitialValue(valueType: string, value: unknown): string | number | boolean | undefined {
  if (valueType === 'bool') return value === true || value === 'true'
  if (valueType === 'int') {
    const candidate = typeof value === 'number' ? value : Number(value)
    return Number.isSafeInteger(candidate) ? candidate : undefined
  }
  if (value == null) return ''
  return typeof value === 'string' ? value : JSON.stringify(value)
}

export function localDateInputValue(now = new Date()): string {
  const year = now.getFullYear()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
