import type { PriceAdjustment } from '../types'
import { computeAdjustedTotal, computeAdjustedUnitPrice, parseAdjustmentValue } from '../utils/pricing'

type Props = {
  adjustment?: PriceAdjustment
  baseUnitPrice?: number | null
  quantity?: number | null
  currency?: string | null
  onChange: (next: PriceAdjustment) => void
}

function formatMoney(value?: number | null, currency = 'EUR'): string {
  if (value == null) return '-'
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(value)
}

export function PriceAdjustmentControl({
  adjustment,
  baseUnitPrice,
  quantity,
  currency,
  onChange,
}: Props) {
  const mode = adjustment?.mode ?? 'percent'
  const value = adjustment?.value ?? ''
  const effectiveUnitPrice = computeAdjustedUnitPrice(baseUnitPrice, adjustment)
  const effectiveTotal = computeAdjustedTotal(effectiveUnitPrice, quantity)
  const enteredValue = parseAdjustmentValue(value)
  const isClamped = baseUnitPrice != null && mode === 'absolute' && enteredValue != null && enteredValue < baseUnitPrice

  if (baseUnitPrice == null) return null

  return (
    <div className="price-adjustment-card">
      <div className="price-adjustment-header">
        <div>
          <strong>VK-Kalkulation</strong>
        </div>
        <div className="price-adjustment-mode">
          <button
            type="button"
            className={`price-mode-btn ${mode === 'percent' ? 'active' : ''}`}
            onClick={() => onChange({ mode: 'percent', value })}
          >
            Aufschlag %
          </button>
          <button
            type="button"
            className={`price-mode-btn ${mode === 'absolute' ? 'active' : ''}`}
            onClick={() => onChange({ mode: 'absolute', value })}
          >
            VK EUR
          </button>
        </div>
      </div>

      <div className="price-adjustment-body">
        <label className="price-adjustment-input">
          <span>{mode === 'percent' ? 'Aufschlag' : 'VK pro Einheit'}</span>
          <input
            type="number"
            min="0"
            step={mode === 'percent' ? '0.1' : '0.01'}
            value={value}
            onChange={(e) => onChange({ mode, value: e.target.value })}
            placeholder={mode === 'percent' ? '10' : formatMoney(baseUnitPrice, currency ?? 'EUR')}
          />
        </label>

        <div className="price-adjustment-stats">
          <span>EK: {formatMoney(baseUnitPrice, currency ?? 'EUR')}</span>
          <span>VK: {formatMoney(effectiveUnitPrice, currency ?? 'EUR')}</span>
          <span>Gesamt: {formatMoney(effectiveTotal, currency ?? 'EUR')}</span>
        </div>
      </div>

      {isClamped && (
        <div className="price-adjustment-note">
          Der VK wurde auf den EK angehoben, weil er nicht darunter liegen darf.
        </div>
      )}
    </div>
  )
}
