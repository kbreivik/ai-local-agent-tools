/**
 * cardSchemas.jsx — field schema definitions for template-driven card rendering.
 */
import React from 'react'
import { compareSemver } from '../utils/versionCheck'

export const DEFAULT_TEMPLATES = {
  container: {
    header_sub:  ['image'],
    collapsed:   ['running_version', 'built_at', 'version_status', 'uptime'],
    expanded:    ['endpoint', 'volumes', 'pull_date', 'actions'],
    entity_only: ['ports', 'networks', 'ip_addresses'],
    hidden:      [],
  },
  swarm_service: {
    header_sub:  ['image'],
    collapsed:   ['replicas', 'uptime'],
    expanded:    ['ports', 'volumes', 'actions'],
    entity_only: ['networks', 'ip_addresses'],
    hidden:      [],
  },
  proxmox_vm: {
    header_sub:  ['node_type'],
    collapsed:   ['cpu', 'ram', 'status'],
    expanded:    ['disks', 'actions'],
    entity_only: [],
    hidden:      [],
  },
}

export const CONTAINER_SCHEMA = [
  { key: 'image',           label: 'Image',        defaultSection: 'header_sub',  locked: false },
  { key: 'running_version', label: 'Running',       defaultSection: 'collapsed',   locked: false },
  { key: 'built_at',        label: 'Built',         defaultSection: 'collapsed',   locked: false },
  { key: 'version_status',  label: 'Status',        defaultSection: 'collapsed',   locked: false },
  { key: 'uptime',          label: 'Uptime',        defaultSection: 'collapsed',   locked: false },
  { key: 'problem',         label: 'Problem',       defaultSection: 'collapsed',   locked: true  },
  { key: 'endpoint',        label: 'Endpoint',      defaultSection: 'expanded',    locked: false },
  { key: 'pull_date',       label: 'Pulled',        defaultSection: 'expanded',    locked: false },
  { key: 'volumes',         label: 'Volumes',       defaultSection: 'expanded',    locked: false },
  { key: 'auto_update',     label: 'Auto-update',   defaultSection: 'expanded',    locked: false },
  { key: 'ports',           label: 'Ports',         defaultSection: 'entity_only', locked: false },
  { key: 'networks',        label: 'Networks',      defaultSection: 'entity_only', locked: false },
  { key: 'ip_addresses',    label: 'Internal IPs',  defaultSection: 'entity_only', locked: false },
  { key: 'actions',         label: 'Actions',       defaultSection: 'expanded',    locked: true  },
]

const S = {
  row:   { display: 'flex', justifyContent: 'space-between', fontSize: 9, marginBottom: 2 },
  label: { color: 'var(--text-3)' },
  value: { fontFamily: 'var(--font-mono)', color: 'var(--text-2)' },
  pill:  (bg, fg) => ({ fontSize: 8, padding: '1px 6px', borderRadius: 2, background: bg, color: fg }),
}

export const CONTAINER_FIELD_RENDERERS = {
  image: {
    renderHeaderSub: ({ data }) => {
      const parts = (data.image || '').split('/')
      return parts[parts.length - 1] || ''
    },
    renderCollapsed: ({ data }) => {
      const parts = (data.image || '').split('/')
      const short = parts[parts.length - 1] || ''
      if (!short) return null
      return React.createElement('div', {
        style: { fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', marginTop: 1 }
      }, short)
    },
  },

  running_version: {
    renderCollapsed: ({ data }) => !data.running_version ? null :
      React.createElement('div', { style: S.row },
        React.createElement('span', { style: S.label }, 'Running'),
        React.createElement('span', { style: S.value }, data.running_version)
      ),
    renderExpanded: ({ data }) => !data.running_version ? null :
      React.createElement('div', { style: S.row },
        React.createElement('span', { style: S.label }, 'Running'),
        React.createElement('span', { style: S.value }, data.running_version)
      ),
  },

  built_at: {
    renderCollapsed: ({ data }) => !data.built_at ? null :
      React.createElement('div', { style: S.row },
        React.createElement('span', { style: S.label }, 'Built'),
        React.createElement('span', { style: S.value }, data.built_at.slice(0, 10))
      ),
    renderExpanded: ({ data }) => !data.built_at ? null :
      React.createElement('div', { style: S.row },
        React.createElement('span', { style: S.label }, 'Built'),
        React.createElement('span', { style: S.value }, data.built_at.slice(0, 10))
      ),
  },

  version_status: {
    renderCollapsed: ({ data, state = {} }) => {
      const { tags = [], tagsLoading = false, tagsError = null, updateStatus = null } = state
      if (!data.running_version) return null
      const severity = (tags[0]) ? compareSemver(data.running_version, tags[0]) : null
      const hasUpdate = severity === 'major' || severity === 'minor' || severity === 'patch'

      let badge = null
      if (tagsLoading) {
        badge = React.createElement('span', { style: S.pill('var(--bg-3)', 'var(--text-3)') }, '…')
      } else if (!tagsError && !tags.length && updateStatus?.update_available === false) {
        badge = React.createElement('span', { style: S.pill('rgba(0,170,68,0.1)', 'var(--green)') }, '✓ latest')
      } else if (!tagsError && !tags.length && updateStatus?.update_available === true) {
        badge = React.createElement('span', { style: S.pill('rgba(204,136,0,0.12)', 'var(--amber)') }, '⬆ update')
      } else if (severity === 'current') {
        badge = React.createElement('span', { style: S.pill('rgba(0,170,68,0.1)', 'var(--green)') }, '✓ latest')
      } else if (hasUpdate) {
        const bg = severity === 'major' ? 'rgba(204,40,40,0.12)' : 'rgba(204,136,0,0.12)'
        const fg = severity === 'major' ? 'var(--red)' : 'var(--amber)'
        badge = React.createElement('span', { style: S.pill(bg, fg) }, `⬆ ${tags[0]} ${severity}`)
      }

      if (!badge) return null
      return React.createElement('div', { style: S.row },
        React.createElement('span', { style: S.label }, 'Status'),
        badge
      )
    },
  },

  uptime: {
    renderCollapsed: ({ data }) => {
      const v = data.uptime || (data.running_replicas != null ? `${data.running_replicas}/${data.desired_replicas} replicas` : null)
      if (!v) return null
      return React.createElement('div', { style: S.row },
        React.createElement('span', { style: S.label }, 'Uptime'),
        React.createElement('span', { style: S.value }, v)
      )
    },
  },

  problem: {
    renderCollapsed: ({ data }) => !data.problem ? null :
      React.createElement('div', {
        style: { fontSize: 9, padding: '1px 6px', borderRadius: 2, background: 'var(--red-dim)', color: 'var(--red)', marginTop: 2 }
      }, `⚠ ${data.problem}`),
  },

  endpoint: {
    renderExpanded: ({ data }) => {
      const browserHost = typeof window !== 'undefined' ? window.location.hostname : ''
      const isLoopback = !browserHost || browserHost === 'localhost' || browserHost === '127.0.0.1'
      const hostIp = isLoopback ? (window.__agentHostIp || browserHost) : browserHost
      const ports = data.ports || []
      let externalPort = null
      for (const p of ports) {
        const hostPart = p.split('→')[0]?.trim()
        if (!hostPart || hostPart.startsWith('127.') || hostPart.startsWith('0.0.0')) continue
        externalPort = hostPart.includes(':') ? hostPart.split(':').pop() : hostPart
        break
      }
      const port = externalPort || data.ip_port?.split(':')[1]
      if (!port) return null
      const href = `http://${hostIp}:${port}`
      return React.createElement('div', { style: { fontSize: 10, fontFamily: 'var(--font-mono)', marginBottom: 4 } },
        React.createElement('span', { style: { fontSize: 9, color: 'var(--text-3)' } }, 'endpoint '),
        React.createElement('a', { href, target: '_blank', rel: 'noopener noreferrer', style: { color: 'var(--cyan)' }, onClick: e => e.stopPropagation() }, `${hostIp}:${port}`)
      )
    },
  },

  pull_date: {
    renderExpanded: ({ data }) => {
      if (!data.last_pull_at) return null
      const age = Date.now() - new Date(data.last_pull_at).getTime()
      const mins = Math.round(age / 60000)
      const label = mins < 60 ? `${Math.max(1, mins)}m ago` : mins < 1440 ? `${Math.floor(mins / 60)}h ago` : `${Math.floor(mins / 1440)}d ago`
      return React.createElement('div', { style: S.row },
        React.createElement('span', { style: S.label }, 'Pulled'),
        React.createElement('span', { style: S.value }, label)
      )
    },
  },

  volumes: {
    renderExpanded: ({ data, state = {} }) => {
      const vols = data.volumes || []
      if (!vols.length) return null
      const { VolBar } = state
      if (!VolBar) return null
      return React.createElement(React.Fragment, null, ...vols.map(v =>
        React.createElement(VolBar, { key: v.name || v.mountpoint, vol: v })
      ))
    },
  },

  auto_update: {
    renderExpanded: ({ data, state = {} }) => {
      if (!data.name?.includes('hp1_agent') || !data.image?.startsWith('ghcr.io/')) return null
      const { AutoUpdateToggle } = state
      return AutoUpdateToggle ? React.createElement(AutoUpdateToggle) : null
    },
  },

  ports: {
    renderExpanded: ({ data }) => {
      const ports = data.ports || []
      if (!ports.length) return null
      return React.createElement('div', { style: { fontSize: 10, fontFamily: 'var(--font-mono)', marginBottom: 4 } },
        React.createElement('span', { style: { fontSize: 9, color: 'var(--text-3)' } }, 'ports '),
        React.createElement('span', { style: { color: 'var(--text-3)' } }, ports.join(' · '))
      )
    },
  },

  networks: {
    renderExpanded: ({ data }) => {
      const nets = data.networks || []
      if (!nets.length) return null
      return React.createElement('div', { style: { fontSize: 10, fontFamily: 'var(--font-mono)', marginBottom: 4 } },
        React.createElement('span', { style: { fontSize: 9, color: 'var(--text-3)' } }, 'networks '),
        React.createElement('span', { style: { color: 'var(--text-3)' } }, nets.join(' · '))
      )
    },
  },

  ip_addresses: {
    renderExpanded: ({ data }) => {
      const ips = data.ip_addresses || []
      if (!ips.length) return null
      return React.createElement('div', { style: { fontSize: 10, fontFamily: 'var(--font-mono)', marginBottom: 4, color: 'var(--text-3)' } },
        React.createElement('span', { style: { fontSize: 9, color: 'var(--text-3)' } }, 'int.ips '),
        ips.join(' · ')
      )
    },
  },

  actions: {
    renderExpanded: ({ state = {} }) => {
      const { ActionsBlock } = state
      return ActionsBlock ? React.createElement(ActionsBlock) : null
    },
  },
}

export const SWARM_SERVICE_SCHEMA = [
  { key: 'image',        label: 'Image',     defaultSection: 'header_sub',  locked: false },
  { key: 'replicas',     label: 'Replicas',  defaultSection: 'collapsed',   locked: false },
  { key: 'uptime',       label: 'Uptime',    defaultSection: 'collapsed',   locked: false },
  { key: 'problem',      label: 'Problem',   defaultSection: 'collapsed',   locked: true  },
  { key: 'ports',        label: 'Ports',     defaultSection: 'expanded',    locked: false },
  { key: 'volumes',      label: 'Volumes',   defaultSection: 'expanded',    locked: false },
  { key: 'networks',     label: 'Networks',  defaultSection: 'entity_only', locked: false },
  { key: 'ip_addresses', label: 'Int. IPs',  defaultSection: 'entity_only', locked: false },
  { key: 'actions',      label: 'Actions',   defaultSection: 'expanded',    locked: true  },
]

export const SWARM_FIELD_RENDERERS = {
  image:        CONTAINER_FIELD_RENDERERS.image,
  problem:      CONTAINER_FIELD_RENDERERS.problem,
  ports:        CONTAINER_FIELD_RENDERERS.ports,
  networks:     CONTAINER_FIELD_RENDERERS.networks,
  ip_addresses: CONTAINER_FIELD_RENDERERS.ip_addresses,
  actions:      CONTAINER_FIELD_RENDERERS.actions,

  replicas: {
    renderCollapsed: ({ data }) => {
      const r = data.running_replicas
      const d = data.desired_replicas
      if (r == null) return null
      return React.createElement('div', { style: S.row },
        React.createElement('span', { style: S.label }, 'Replicas'),
        React.createElement('span', { style: { fontFamily: 'var(--font-mono)', color: r === d ? 'var(--green)' : 'var(--amber)' } }, `${r}/${d}`)
      )
    },
  },

  uptime: {
    renderCollapsed: ({ data }) => !data.uptime ? null :
      React.createElement('div', { style: S.row },
        React.createElement('span', { style: S.label }, 'Uptime'),
        React.createElement('span', { style: S.value }, data.uptime)
      ),
  },
}
