const DIN_DESCRIPTIONS: Record<string, string> = {
  'din en 1401': 'Rohrsysteme aus PVC-U für Abwasserleitungen und -kanäle',
  'din en 13476': 'Rohrsysteme aus Kunststoff für erdverlegte Abwasserkanäle (strukturwandig)',
  'din en 1916': 'Rohre und Formstücke aus Beton/Stahlbeton',
  'din en 124': 'Aufsätze und Abdeckungen für Verkehrsflächen',
  'din en 1917': 'Einstiegs- und Kontrollschächte aus Beton',
  'din en 12889': 'Grabenlose Verlegung und Prüfung von Abwasserleitungen',
  'din en 1610': 'Einbau und Prüfung von Abwasserleitungen und -kanälen',
  'din en 476': 'Allgemeine Anforderungen an Entwässerungssysteme',
  'din en 295': 'Steinzeugrohre für Abwasserleitungen',
  'din en 598': 'Rohre, Formstücke und Zubehör aus duktilem Gusseisen',
  'din en 1329': 'Rohrsysteme aus PP für Abwasserleitungen im Gebäude',
  'din en 12666': 'Rohrsysteme aus PE für erdverlegte drucklose Abwasserkanäle',
  'din 4060': 'Straßenabläufe für Regenwasser',
  'din 19534': 'Kontrollschächte aus Kunststoff',
  'din 4263': 'Prüfung von Entwässerungsanlagen',
  'din en 681': 'Elastomer-Dichtungen für Rohrleitungen',
  'din en 12201': 'Rohrsysteme aus PE für die Wasserversorgung',
  'din en 12007': 'Gasinfrastruktur - Rohrleitungen',
  'din en 1852': 'Rohrsysteme aus PP für Abwasserleitungen (erdverlegt)',
  'din en 13598': 'Schächte und Inspektionskammern aus PVC-U, PP und PE',
}

type Props = {
  norm: string
  className?: string
}

export function DinBadge({ norm, className = '' }: Props) {
  const normalized = norm.toLowerCase().trim()
  const description = Object.entries(DIN_DESCRIPTIONS).find(([key]) =>
    normalized.includes(key) || key.includes(normalized)
  )?.[1]

  return (
    <span className={`din-badge ${className}`}>
      <span className="din-badge-text">{norm}</span>
      {description && (
        <span className="din-badge-tooltip">{description}</span>
      )}
    </span>
  )
}
