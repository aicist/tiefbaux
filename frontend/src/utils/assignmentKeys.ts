export function primaryAssignmentKey(positionId: string): string {
  return `${positionId}::primary`
}

export function additionalAssignmentKey(positionId: string, artikelId: string): string {
  return `${positionId}::additional::${artikelId}`
}

export function componentSelectionKey(positionId: string, componentName: string): string {
  return `${positionId}::${componentName}`
}

export function componentAssignmentKey(positionId: string, componentName: string): string {
  return `${positionId}::component::${componentName}`
}
