import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import AgentDiagnostics from '../AgentDiagnostics'

describe('AgentDiagnostics', () => {
  it('renders budget when agent_type is investigate', () => {
    const { container } = render(<AgentDiagnostics diag={{
      agent_type: 'investigate',
      tools_used: 5, budget: 16, budget_pct: 31,
      has_diagnosis: false,
      zero_streaks: {}, pivot_nudges_fired: [],
    }} />)
    expect(container.textContent).toContain('5')
    expect(container.textContent).toContain('16')
    expect(container.textContent.toLowerCase()).toContain('not yet')
  })

  it('renders nothing for observe agent', () => {
    const { container } = render(<AgentDiagnostics diag={{
      agent_type: 'observe',
      tools_used: 3, budget: 8,
    }} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when diag is null', () => {
    const { container } = render(<AgentDiagnostics diag={null} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows zero-streak badge when tool hits 3+ zeros', () => {
    const { container } = render(<AgentDiagnostics diag={{
      agent_type: 'investigate',
      tools_used: 7, budget: 16,
      has_diagnosis: false,
      zero_streaks: { elastic_search_logs: 4 },
      pivot_nudges_fired: [],
    }} />)
    expect(container.textContent).toContain('×4')
  })

  it('shows DIAGNOSIS emitted state when has_diagnosis is true', () => {
    const { container } = render(<AgentDiagnostics diag={{
      agent_type: 'investigate',
      tools_used: 10, budget: 16,
      has_diagnosis: true,
      zero_streaks: {}, pivot_nudges_fired: [],
    }} />)
    expect(container.textContent).toContain('emitted')
  })

  it('shows SUBTASK PROPOSED indicator', () => {
    const { container } = render(<AgentDiagnostics diag={{
      agent_type: 'investigate',
      tools_used: 12, budget: 16,
      has_diagnosis: false,
      zero_streaks: {}, pivot_nudges_fired: [],
      subtask_proposed: true,
    }} />)
    expect(container.textContent).toContain('SUBTASK PROPOSED')
  })

  it('shows pivot nudge counter', () => {
    const { container } = render(<AgentDiagnostics diag={{
      agent_type: 'investigate',
      tools_used: 8, budget: 16,
      has_diagnosis: false,
      zero_streaks: {},
      pivot_nudges_fired: ['elastic_search_logs'],
    }} />)
    expect(container.textContent).toContain('pivot nudge')
  })
})
