import { describe, expect, it } from 'vitest'
import { normalizeUserCreateValues, validateOptionalFeishuOpenId } from './userForm'

describe('user create form payload', () => {
  it('omits a cleared optional Feishu identity instead of sending an invalid empty string', () => {
    expect(normalizeUserCreateValues({
      username: 'zoey',
      password: 'password123',
      role_code: 'member',
      feishu_open_id: '   ',
    })).toEqual({
      username: 'zoey',
      password: 'password123',
      role_code: 'member',
      feishu_open_id: undefined,
    })
  })

  it('rejects a prefixed but too-short Feishu identity before submission', async () => {
    await expect(validateOptionalFeishuOpenId('ou_a')).rejects.toThrow('8–128')
    await expect(validateOptionalFeishuOpenId('')).resolves.toBeUndefined()
    await expect(validateOptionalFeishuOpenId('   ')).resolves.toBeUndefined()
    await expect(validateOptionalFeishuOpenId('ou_12345')).resolves.toBeUndefined()
    await expect(validateOptionalFeishuOpenId('xx_12345')).rejects.toThrow('ou_ 或 ou-')
  })
})
