import { describe, expect, it } from 'vitest'
import { canResearchProposal } from './model'

describe('proposal actions', () => {
  it('never offers another AI research run while one is already running', () => {
    expect(canResearchProposal('draft')).toBe(true)
    expect(canResearchProposal('reviewed')).toBe(true)
    expect(canResearchProposal('researching')).toBe(false)
    expect(canResearchProposal('approved')).toBe(false)
    expect(canResearchProposal('rejected')).toBe(false)
  })
})
