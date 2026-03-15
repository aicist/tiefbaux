import type { PriceAdjustment } from '../types'

function roundMoney(value: number): number {
  return Math.round(value * 100) / 100
}

export function parseAdjustmentValue(value: string): number | null {
  if (!value.trim()) return null
  const normalized = value.replace(',', '.')
  const parsed = Number(normalized)
  return Number.isFinite(parsed) ? parsed : null
}

export function computeAdjustedUnitPrice(
  baseUnitPrice?: number | null,
  adjustment?: PriceAdjustment | null,
): number | null {
  if (baseUnitPrice == null) return null
  const parsedValue = parseAdjustmentValue(adjustment?.value ?? '')
  if (parsedValue == null) return roundMoney(baseUnitPrice)

  if (adjustment?.mode === 'absolute') {
    return roundMoney(Math.max(baseUnitPrice, parsedValue))
  }

  return roundMoney(Math.max(baseUnitPrice, baseUnitPrice * (1 + parsedValue / 100)))
}

export function computeAdjustedTotal(
  unitPrice?: number | null,
  quantity?: number | null,
): number | null {
  if (unitPrice == null) return null
  const qty = quantity ?? 1
  return roundMoney(unitPrice * qty)
}

export function isAdjustedPrice(
  baseUnitPrice?: number | null,
  adjustedUnitPrice?: number | null,
): boolean {
  if (baseUnitPrice == null || adjustedUnitPrice == null) return false
  return Math.abs(adjustedUnitPrice - baseUnitPrice) >= 0.01
}
