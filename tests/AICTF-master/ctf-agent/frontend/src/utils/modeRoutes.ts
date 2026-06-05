import type { AgentMode } from '../types'

export function getModeHomePath(mode: AgentMode): string {
  switch (mode) {
    case 'reverse':
      return '/reverse-lab'
    case 'audit':
      return '/audit/dashboard'
    case 'pentest':
      return '/pentest/dashboard'
    case 'inspection':
      return '/inspection/dashboard'
    case 'ctf':
    default:
      return '/dashboard'
  }
}
