import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import { VersionSelect, isRunningVersion } from '../ServiceCards'

function getOption(container, value) {
  return Array.from(container.querySelectorAll('option')).find(o => o.value === value)
}

describe('VersionSelect', () => {
  it('running version is marked in dropdown', () => {
    const { container } = render(
      <VersionSelect
        tags={['2.34.6', '2.34.5', '2.34.4']}
        value="2.34.6"
        onChange={() => {}}
        runningTag="2.34.4"
      />
    )
    const runningOption = getOption(container, '2.34.4')
    expect(runningOption.textContent).toContain('▶')
    expect(runningOption.textContent).toContain('running')
    expect(runningOption.classList.contains('version-row')).toBe(true)
  })

  it('non-running versions have no marker', () => {
    const { container } = render(
      <VersionSelect
        tags={['2.34.6', '2.34.5', '2.34.4']}
        value="2.34.6"
        onChange={() => {}}
        runningTag="2.34.4"
      />
    )
    const other = getOption(container, '2.34.5')
    expect(other.textContent).not.toContain('▶')
    expect(other.textContent).not.toContain('running')
  })

  it('renders nothing special when runningTag is unset', () => {
    const { container } = render(
      <VersionSelect
        tags={['2.34.6', '2.34.5']}
        value="2.34.6"
        onChange={() => {}}
        runningTag={null}
      />
    )
    for (const opt of container.querySelectorAll('option')) {
      expect(opt.textContent).not.toContain('▶')
      expect(opt.textContent).not.toContain('running')
    }
  })
})

describe('isRunningVersion', () => {
  it('matches identical tags', () => {
    expect(isRunningVersion('2.34.4', '2.34.4')).toBe(true)
  })

  it('matches across v-prefix normalisation', () => {
    expect(isRunningVersion('2.34.4', 'v2.34.4')).toBe(true)
    expect(isRunningVersion('v2.34.4', '2.34.4')).toBe(true)
  })

  it('returns false for different versions', () => {
    expect(isRunningVersion('2.34.4', '2.34.5')).toBe(false)
  })

  it('returns false when either input is missing', () => {
    expect(isRunningVersion('', '2.34.4')).toBe(false)
    expect(isRunningVersion('2.34.4', null)).toBe(false)
    expect(isRunningVersion(null, null)).toBe(false)
  })
})
