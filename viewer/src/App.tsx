import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { createPortal } from 'react-dom'
import './App.css'

type ProductRow = {
  id: string
  gate: number | null
  adult: string | null
  cells: string[]
}

// Display-only label override. When SD is active, the AdrenoFuel row in
// slow-ox buckets (1, 2) renders as ThyroSpark — the dose is identical
// (per writer.py get_dose), but the visible label changes so reviewers
// can tell at a glance that the SD swap is in effect.
type DisplayRow = ProductRow & { displayId?: string }

type Bucket = {
  name: string
  products: ProductRow[]
}

type DisplayBucket = {
  name: string
  products: DisplayRow[]
}

type Data = {
  ages: number[]
  buckets: Bucket[]
}

type DisplayData = {
  ages: number[]
  buckets: DisplayBucket[]
}

type Overrides = Record<string, string>

function doseKey(bIdx: number, pIdx: number, aIdx: number): string {
  return `${bIdx}-${pIdx}-${aIdx}`
}

// Products whose dose depends on Na/K ratio (zinc-matrix-pro, na-k-up).
// These share overrides across all buckets that contain the product so
// editing one bucket applies to all (cross-bucket mirror, option a1:
// first edit wins, no-op on subsequent edits until the override is cleared).
const NAK_DRIVEN_PRODUCTS = new Set(['zinc-matrix-pro', 'na-k-up'])

// Resolve the override key for a cell. For Na/K-driven products (zinc,
// na-k-up) the key is scoped per-slider value so an override at 8.0
// doesn't apply at 2.5 (the dose is slider-driven). For other products
// the key is per-bucket (oxidation + Na-K + 4-lows are bucket-level).
function overrideKey(
  bIdx: number,
  pIdx: number,
  aIdx: number,
  productId: string,
  sliderValue: number,
): string {
  if (NAK_DRIVEN_PRODUCTS.has(productId)) {
    // Round to 1 decimal to avoid floating-point drift (2.5 + 0 + 0 = 2.5
    // but 2.5 - 0.0001 + 0.0001 ≠ 2.5 in JS).
    return `${productId}-${aIdx}-${sliderValue.toFixed(1)}`
  }
  return doseKey(bIdx, pIdx, aIdx)
}

// Migrate legacy per-bucket zinc/na-k-up overrides to the shared format.
// Old format: "0-3-7" -> "1 cap" (zinc at bucket 0, pIdx 3, age 7)
// New format: "zinc-matrix-pro-7" -> "1 cap"
// If multiple buckets have an override for the same (product, age), the
// first one wins (deterministic, preserves user's earliest edit).
// All other products are kept as-is (per-bucket scoped).
function migrateOverrides(raw: Record<string, string>): Record<string, string> {
  const migrated: Record<string, string> = {}

  // First pass: copy all non-NAK-driven products as-is
  for (const [key, value] of Object.entries(raw)) {
    migrated[key] = value
  }

  // Second pass: explicitly migrate known NAK product keys to shared format
  // Zinc matrix pro positions: bucket 0 pIdx 3, bucket 2 pIdx 2, bucket 4 pIdx 1
  // Na/K Up positions: bucket 1 pIdx 3, bucket 3 pIdx 2, bucket 5 pIdx 1
  const ZINC_POSITIONS = new Set(['0-3', '2-2', '4-1'])
  const NAK_UP_POSITIONS = new Set(['1-3', '3-2', '5-1'])

  // Default slider position to scope legacy overrides to. Since we don't
  // know which slider position the user was on when they saved the
  // override, we use 2.5 (the most common anchor — matches the default
  // panel Na/K for a "balanced" patient). If the user later moves the
  // slider to 2.5, they see their override; otherwise they see the
  // slider's auto-computed value.
  const DEFAULT_NAK = '2.5'

  for (const key of Object.keys(migrated)) {
    const parts = key.split('-')
    if (parts.length !== 3) continue
    const [bIdx, pIdx, aIdx] = parts
    const pos = `${bIdx}-${pIdx}`

    let productId: string | null = null
    if (ZINC_POSITIONS.has(pos)) productId = 'zinc-matrix-pro'
    else if (NAK_UP_POSITIONS.has(pos)) productId = 'na-k-up'

    if (productId) {
      // Slider-scoped key: {productId}-{aIdx}-{nakRatio}
      const newKey = `${productId}-${aIdx}-${DEFAULT_NAK}`
      // First-edit-wins: if we already have a value at newKey, skip
      if (!(newKey in migrated)) {
        migrated[newKey] = migrated[key]
      }
      delete migrated[key]
    }
  }

  // Third pass: legacy unscoped keys like "zinc-matrix-pro-7" (no -N.N
  // suffix) need to be migrated to scoped format too. These were saved
  // before slider-scoping was introduced.
  for (const key of Object.keys(migrated)) {
    const m = key.match(/^(zinc-matrix-pro|na-k-up)-(\d+)$/)
    if (m) {
      const productId = m[1]
      const aIdx = m[2]
      const newKey = `${productId}-${aIdx}-${DEFAULT_NAK}`
      if (!(newKey in migrated)) {
        migrated[newKey] = migrated[key]
      }
      delete migrated[key]
    }
  }

  return migrated
}

function doseClass(cell: string | undefined | null): string {
  if (!cell || cell === '—') return 'dose-empty'
  const [am, pm] = (cell || '').split('·')
  const parse = (s: string | undefined): number => {
    if (!s) return 0
    const m = s.match(/([½⅓¼⅔¾])|(\d+)/)
    if (!m) return 0
    if (m[1]) {
      const fracs: Record<string, number> = { '¼': 0.25, '⅓': 0.33, '½': 0.5, '⅔': 0.67, '¾': 0.75 }
      return fracs[m[1]] ?? 0
    }
    return parseFloat(m[2])
  }
  const total = parse(am) + parse(pm)
  if (total === 0) return 'dose-zero'
  if (total < 1) return 'dose-quarter'
  if (total < 2) return 'dose-half'
  if (total < 3) return 'dose-one'
  if (total < 4) return 'dose-two'
  return 'dose-heavy'
}

function isValidDose(s: string): boolean {
  // Lenient: accept any string that COULD plausibly be a dose. We don't
  // reject character-by-character during typing — that would break the
  // user mid-word. Validation only matters at commit time.
  if (!s) return true
  if (s.length > 30) return false
  // Block characters that would never appear in a dose string
  const forbidden = /[<>;{}`\[\]\\]/
  return !forbidden.test(s)
}

// Convert user-typed fractions to unicode. "1/4" → "¼", "1 1/2" → "1½", etc.
// Applied on every onChange so the user sees the conversion immediately.
const FRACTION_MAP: Record<string, string> = {
  '1/4': '¼',
  '1/3': '⅓',
  '1/2': '½',
  '2/3': '⅔',
  '3/4': '¾',
  '1/8': '⅛',
  '3/8': '⅜',
  '5/8': '⅝',
  '7/8': '⅞',
}

// Try to convert "1/4" or "1 1/2" patterns anywhere in the input to unicode.
// Returns the original string if no conversion applies.
function normalizeFractions(s: string): string {
  if (!s) return s
  let out = s
  // Mixed numbers: "1 1/2" → "1½" (must run before plain fractions)
  for (const [frac, uni] of Object.entries(FRACTION_MAP)) {
    // Match digit + space + fraction, e.g., "1 1/2"
    const mixed = new RegExp(`(\\d+)\\s+${frac.replace('/', '\\/')}(?!\\d)`, 'g')
    out = out.replace(mixed, `$1${uni}`)
  }
  // Plain fractions: "1/2" → "½" (only if not preceded by a digit — that would
  // mean a fraction as part of a larger expression, leave alone)
  for (const [frac, uni] of Object.entries(FRACTION_MAP)) {
    const re = new RegExp(`(?<![\\d])${frac.replace('/', '\\/')}`, 'g')
    out = out.replace(re, uni)
  }
  return out
}

const STORAGE_KEY = 'htma-kids-matrix-overrides-v2'
const LEGACY_V1_STORAGE_KEY = 'htma-kids-matrix-overrides-v1'

// Common dose values for quick-set. Just the number — no "cap" suffix.
const QUICK_DOSES: string[] = [
  '0', '¼', '⅓', '½', '⅔', '¾',
  '1', '1½', '2', '2½', '3', '4', '5', '6',
]

// ── Na/K ratio dose dial (Luke 2026-09-09) ──────────────────────────────

type DoseSlot = { am: string; noon: string; pm: string }
type Anchor = { na_k_max: number | null; dose: DoseSlot }

// Parse "1 cap", "2 caps", "0" → numeric cap count.
function parseCap(s: string): number {
  if (!s || s === '0') return 0
  try {
    return parseFloat(s.split()[0])
  } catch {
    return 0
  }
}

// Format a numeric cap count back to a dose string. Round to nearest integer
// (half-up), matching the production `_format_caps` semantics in doses.py.
function formatCap(n: number): string {
  const r = Math.round(n)
  return `${r}`
}

// Format a numeric cap count as a human-readable dose string. Returns just
// the number for cells (no "cap" suffix), or "1 cap" / "2 caps" etc. for
// the Adult column where the suffix is informative.
function formatDose(n: number, withSuffix: boolean = true): string {
  const r = Math.round(n)
  if (!withSuffix) return `${r}`
  if (r === 0) return '0'
  if (r === 1) return '1 cap'
  return `${r} caps`
}

// Linear interpolation of AM/NOON/PM between anchor points.
// Mirrors lab_pipeline/interpreter/doses.py:linear_interpolate_dose but
// in JS. Used to compute zinc-matrix-pro and na-k-up doses at the
// slider's current Na/K value.
function linearInterpolateDose(anchors: Anchor[], nak: number): DoseSlot {
  // Find the segment: first anchor whose na_k_max is None or na_k <= na_k_max
  let segIdx = -1
  for (let i = 0; i < anchors.length; i++) {
    const max = anchors[i].na_k_max
    if (max === null || nak <= max) {
      segIdx = i
      break
    }
  }
  if (segIdx === -1) segIdx = anchors.length - 1

  const cur = anchors[segIdx]
  const curDose = cur.dose

  if (segIdx === 0 || cur.na_k_max === null) {
    return { am: formatCap(parseCap(curDose.am)), noon: formatCap(parseCap(curDose.noon)), pm: formatCap(parseCap(curDose.pm)) }
  }

  const prev = anchors[segIdx - 1]
  const prevDose = prev.dose
  if (prev.na_k_max === null || cur.na_k_max === null || cur.na_k_max === prev.na_k_max) {
    return { am: formatCap(parseCap(curDose.am)), noon: formatCap(parseCap(curDose.noon)), pm: formatCap(parseCap(curDose.pm)) }
  }
  const t = (nak - (prev.na_k_max as number)) / ((cur.na_k_max as number) - (prev.na_k_max as number))
  const tc = Math.max(0, Math.min(1, t))
  const am = parseCap(prevDose.am) + (parseCap(curDose.am) - parseCap(prevDose.am)) * tc
  const noon = parseCap(prevDose.noon) + (parseCap(curDose.noon) - parseCap(prevDose.noon)) * tc
  const pm = parseCap(prevDose.pm) + (parseCap(curDose.pm) - parseCap(prevDose.pm)) * tc
  return { am: formatCap(am), noon: formatCap(noon), pm: formatCap(pm) }
}

// Check if the current Na/K value matches an anchor exactly (within float
// tolerance). Used to show the "active anchor" badge.
function findActiveAnchor(anchors: Anchor[], nak: number): Anchor | null {
  for (const a of anchors) {
    if (a.na_k_max !== null && Math.abs(a.na_k_max - nak) < 0.001) return a
  }
  // Also match the ceiling anchor when nak is very high
  const ceiling = anchors[anchors.length - 1]
  if (ceiling.na_k_max === null && nak > (anchors[anchors.length - 2]?.na_k_max ?? 0)) {
    return ceiling
  }
  return null
}

// ── Kids dose scaling (Luke 2026-09-08) ───────────────────────────────────
// Port of lab_pipeline/interpreter/kids_dosing.py — used to apply age
// scaling to adult doses (zinc, na-k-up) computed from the Na/K slider.

const KIDS_FACTOR_ANCHORS: [number, number][] = [
  [0.0, 0.0],
  [6.0, 0.5],
  [12.0, 0.75],
  [18.0, 1.0],
]

function kidsFactor(age: number | null | undefined): number {
  if (age === null || age === undefined) return 1.0
  if (age >= 18) return 1.0
  if (age <= 0) return 0.0
  for (let i = 0; i < KIDS_FACTOR_ANCHORS.length - 1; i++) {
    const [aLo, fLo] = KIDS_FACTOR_ANCHORS[i]
    const [aHi, fHi] = KIDS_FACTOR_ANCHORS[i + 1]
    if (aLo <= age && age <= aHi) {
      const t = (age - aLo) / (aHi - aLo)
      return fLo + (fHi - fLo) * t
    }
  }
  return 1.0
}

// Floor a value to the nearest 1/4, 1/3, 1/2, or whole cap.
function floorToFraction(n: number): number {
  if (n < 0) return 0
  const eps = 1e-9
  if (n < 0.125) return 0
  if (n < 1 / 3) return Math.floor(n * 4 + eps) / 4
  if (n < 0.5) return Math.floor(n * 3 + eps) / 3
  if (n < 1) return Math.floor(n * 2 + eps) / 2
  return Math.floor(n + eps)
}

function formatFraction(n: number): string {
  if (n === 0) return '0'
  const r = Math.round(n * 100) / 100
  const fracs: Record<string, string> = {
    '0.25': '¼', '0.33': '⅓', '0.5': '½', '0.67': '⅔', '0.75': '¾',
  }
  const k = String(r)
  if (fracs[k]) return `${fracs[k]}`
  if (r === Math.floor(r)) {
    return `${Math.floor(r)}`
  }
  const whole = Math.floor(r)
  const frac = Math.round((r - whole) * 100) / 100
  const fracStr = fracs[String(frac)] ?? `${frac}`
  return `${whole}${fracStr}`
}

// Strip " cap" / " caps" suffix from a dose string. We display just the
// number everywhere — no unit suffix.
function stripCap(s: string | null | undefined): string {
  if (!s) return ''
  return s.replace(/\s*caps?\b/g, '').trim()
}

// Apply kid dose reduction: age-scale the adult AM/NOON/PM, strip NOON
// (NOON→PM via MAX), floor to fraction ladder.
function kidsDose(adultAm: string, adultNoon: string, adultPm: string, age: number): [string, string, string] {
  // Adult path: untouched 3-slot dose (only when age is None or >18).
  // Mirrors Python `is_kid(age) -> age is not None and age <= 18` — so
  // age 18 is still treated as a kid and gets the 2-slot simplification.
  if (age === null || age === undefined || age > 18) {
    return [adultAm || '0', adultNoon || '0', adultPm || '0']
  }
  const factor = kidsFactor(age)
  const noonCaps = parseCap(adultNoon)
  const pmCaps = parseCap(adultPm)
  const pmMerged = Math.max(noonCaps, pmCaps)
  const amCaps = parseCap(adultAm)
  const amScaled = amCaps * factor
  const pmScaled = pmMerged * factor
  return [
    formatFraction(floorToFraction(amScaled)),
    '0',
    formatFraction(floorToFraction(pmScaled)),
  ]
}

// Type augmentation for products that carry a dose_schedule
type ProductRowWithSchedule = ProductRow & {
  dose_schedule?: { anchors: Anchor[] }
}

function App() {
  const [baseData, setBaseData] = useState<Data | null>(null)
  const [overrides, setOverrides] = useState<Overrides>({})
  const [activeBucket, setActiveBucket] = useState<string>('')
  const [editMode, setEditMode] = useState(false)
  const [savedFlash, setSavedFlash] = useState(false)
  const [activeCellKey, setActiveCellKey] = useState<string | null>(null)
  const [pickerHost, setPickerHost] = useState<string | null>(null)  // tracks the cell whose picker is open
  const [loaded, setLoaded] = useState(false)  // gates save effect
  const [sdActive, setSdActive] = useState(false)  // Sympathetic Dominance toggle (slow-ox only)
  const [nakRatio, setNakRatio] = useState<number>(2.5)  // Na/K ratio dial (0.5-8.0)
  const inputsRef = useRef<Record<string, HTMLInputElement | null>>({})

  // Load base matrix
  useEffect(() => {
    fetch('/data.json')
      .then(r => r.json())
      .then((d: Data) => {
        // Strip " cap" / " caps" suffix from all dose strings in the
        // loaded matrix. We display just the number — no unit suffix.
        const stripped: Data = {
          ...d,
          buckets: d.buckets.map(b => ({
            ...b,
            products: b.products.map(p => ({
              ...p,
              adult: stripCap(p.adult),
              cells: p.cells.map(c => stripCap(c)),
            })),
          })),
        }
        setBaseData(stripped)
        if (d.buckets.length > 0) setActiveBucket(d.buckets[0].name)
      })
  }, [])

  // Load overrides from localStorage on mount. Also migrate legacy
  // per-bucket zinc-matrix-pro / na-k-up overrides into a shared
  // cross-bucket format (so all 3 buckets of the same product share one
  // override per age). Migration is safe — runs once on load and writes
  // the migrated data back to localStorage.
  //
  // v2 note (2026-09-12): the data.json is now generated by
  // tools/build_viewer_data.py from the v2 matrix repo. The v1
  // override values are stored in a different key shape and would
  // render incorrectly against the v2 cells. We DELIBERATELY use a
  // new STORAGE_KEY (v2) and purge any leftover v1 overrides on load,
  // so the viewer starts v2 with a clean slate.
  useEffect(() => {
    try {
      // One-shot purge of any leftover v1 overrides from the previous
      // viewer version. Safe to remove: v1 was an eyes-only dial-in
      // tool, not a published system of record.
      if (localStorage.getItem(LEGACY_V1_STORAGE_KEY)) {
        localStorage.removeItem(LEGACY_V1_STORAGE_KEY)
        console.info('[viewer v2] purged legacy v1 overrides from localStorage')
      }

      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        const raw = JSON.parse(stored) as Record<string, string>
        // Normalize stored overrides: strip " cap" / " caps" suffix so
        // existing entries display cleanly alongside the new format.
        const normalized: Record<string, string> = {}
        for (const [k, v] of Object.entries(raw)) {
          normalized[k] = stripCap(v)
        }
        setOverrides(migrateOverrides(normalized))
      }
    } catch (e) {
      console.warn('Failed to load overrides:', e)
    } finally {
      setLoaded(true)
    }
  }, [])

  // Save overrides to localStorage whenever they change (but only AFTER load)
  useEffect(() => {
    if (!loaded) return
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides))
    } catch (e) {
      console.warn('Failed to save overrides:', e)
    }
  }, [overrides, loaded])

  const updateCell = useCallback((bIdx: number, pIdx: number, aIdx: number, value: string, productId?: string) => {
    // Use productId-aware key for zinc/na-k-up so overrides share across
    // buckets. For other products, fall back to bucket-keyed storage.
    // Slider value is passed so the override is scoped per-slider-position.
    const key = productId
      ? overrideKey(bIdx, pIdx, aIdx, productId, nakRatio)
      : doseKey(bIdx, pIdx, aIdx)
    setOverrides(prev => {
      const next = { ...prev }
      // Empty string means "remove my override, restore auto-computed value"
      if (value === '') {
        delete next[key]
      } else {
        // Always store the override when the user explicitly edits. We
        // previously tried to skip "redundant" overrides (where the typed
        // value happened to match the static data.json cell value), but
        // that was wrong: for NAK-driven products the cell display is
        // slider-recomputed, so a typed value that happens to equal the
        // static data.json value at slider=2.5 may still be an explicit
        // override the user wants to keep for that specific slider
        // position. Always preserve the override.
        next[key] = value
      }
      return next
    })
  }, [baseData, nakRatio])

  // Adult-column override handler. Key shape: `adult-{bIdx}-{pIdx}` —
  // per-bucket, no slider scope, no age axis (Adult is the static
  // reference dose at the bucket level). The Adult column drives the
  // kid-scaling math at every age, so editing it changes every cell in
  // the row when the row has no per-age override.
  const updateAdultCell = useCallback((bIdx: number, pIdx: number, value: string) => {
    const key = `adult-${bIdx}-${pIdx}`
    setOverrides(prev => {
      const next = { ...prev }
      if (value === '') {
        delete next[key]
      } else {
        next[key] = value
      }
      return next
    })
  }, [])

  // Helper for resolving the Adult display value: explicit override
  // wins, otherwise the bucket's computed adult (which may itself be
  // slider-interpolated for zinc / na-k-up).
  function resolveAdultDisplay(bIdx: number, pIdx: number, computedAdult: string): string {
    const adultOverride = overrides[`adult-${bIdx}-${pIdx}`]
    return adultOverride ?? computedAdult
  }

  const resetAll = useCallback(() => {
    if (confirm('Clear all manual overrides and restore the auto-generated matrix?')) {
      setOverrides({})
    }
  }, [])

  const exportOverrides = useCallback(() => {
    const json = JSON.stringify(overrides, null, 2)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `htma-kids-matrix-overrides-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
    setSavedFlash(true)
    setTimeout(() => setSavedFlash(false), 2000)
  }, [overrides])

  const importOverrides = useCallback(() => {
    const input = document.createElement('input')
    input.type = 'file'
    input.accept = 'application/json'
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0]
      if (!file) return
      try {
        const text = await file.text()
        const parsed = JSON.parse(text)
        setOverrides(parsed)
        setSavedFlash(true)
        setTimeout(() => setSavedFlash(false), 2000)
      } catch (err) {
        alert('Invalid JSON: ' + (err as Error).message)
      }
    }
    input.click()
  }, [])

  // Apply two display-time mirrors:
  //
  // 1. SLOW-OX BUCKET MIRROR: bucket 1 (Slow+High) and bucket 2 (Slow+Low)
  //    share the same product set EXCEPT for the zinc↔Na/K-Up pair.
  //    For any product present in both buckets, an override set on bucket 1
  //    is mirrored to bucket 2 (and vice-versa). This means the user only
  //    needs to edit one slow-ox bucket and the change carries to the other.
  //    Bucket 2's own override (if any) wins — bucket 1 is only the fallback.
  //
  // 2. SD LABEL SWAP: in slow-ox buckets (1, 2), the AdrenoFuel row is
  //    DISPLAYED AS ThyroSpark because the adult pipeline swaps these two
  //    products when K≤4 (per writer.py get_dose). There is only ONE row —
  //    AdrenoFuel's row becomes ThyroSpark's row visually — so any override
  //    the user sets for AdrenoFuel carries over to ThyroSpark automatically
  //    (the dose is what matters, the product ID is just a label).
  //
  // Buckets 3-6 are unaffected by either mirror.
  //
  // The slow-ox mirror respects the zinc↔Na/K-Up exception: an override on
  // zinc-matrix-pro in bucket 1 does NOT mirror to na-k-up in bucket 2 (and
  // vice versa) because those are different products.
  const data: DisplayData | null = useMemo(() => {
    if (!baseData) return null

    // Build a fast lookup: for each shared product, the same row in the
    // other slow-ox bucket (if any). Used for the bucket mirror.
    //
    // We pair (bIdx, pIdx) -> mirror (bIdx, pIdx) by matching product.id.
    const mirrorPairs: Array<{
      source: [number, number]
      target: [number, number]
    }> = []
    if (baseData.buckets.length >= 2) {
      const b0Products = baseData.buckets[0].products.map((p, pIdx) => [p.id, pIdx] as const)
      const b1Products = baseData.buckets[1].products.map((p, pIdx) => [p.id, pIdx] as const)
      for (const [id0, pIdx0] of b0Products) {
        const match1 = b1Products.find(([id]) => id === id0)
        if (match1) {
          // bucket 1 → bucket 2
          mirrorPairs.push({ source: [0, pIdx0], target: [1, match1[1]] })
          // bucket 2 → bucket 1
          mirrorPairs.push({ source: [1, match1[1]], target: [0, pIdx0] })
        }
      }
    }

    return {
      ...baseData,
      buckets: baseData.buckets.map((b, bIdx) => {
        const isSlowOx = bIdx === 0 || bIdx === 1
        const swapLabels = sdActive && isSlowOx
        return {
          ...b,
          products: b.products.map((p, pIdx): DisplayRow => {
            // SD label swap for the adrenofuel row in slow-ox buckets
            const baseRow: DisplayRow = swapLabels && p.id === 'adrenofuel'
              ? { ...p, displayId: 'thyro-spark (SD swap)' }
              : p
            // Na/K ratio dial (Luke 2026-09-09): for zinc-matrix-pro and
            // na-k-up, also dial the Adult column so the Adult shows the
            // AM/NOON/PM dose at the current Na/K, not the static fallback.
            // Format: "{am}·{noon}·{pm}" with adult cap counts (no kid
            // scaling, NOON kept).
            let adultDisplay = baseRow.adult
            if (p.id === 'zinc-matrix-pro' || p.id === 'na-k-up') {
              const sched = (p as ProductRowWithSchedule).dose_schedule
              if (sched) {
                const adultDose = linearInterpolateDose(sched.anchors, nakRatio)
                adultDisplay = `${adultDose.am}·${adultDose.noon}·${adultDose.pm}`
              }
            }
            return {
              ...baseRow,
              adult: adultDisplay,
              cells: p.cells.map((c, aIdx) => {
                // Two key spaces:
                //   doseKey(bIdx, pIdx, aIdx) — DOM element id, picker focus.
                //   overrideKey()               — override storage (shared
                //                                  across buckets for zinc +
                //                                  na-k-up, per-bucket otherwise).
                const key = doseKey(bIdx, pIdx, aIdx)
                const storageKey = overrideKey(bIdx, pIdx, aIdx, p.id, nakRatio)
                // 1. Own override wins
                let v: string | undefined = overrides[storageKey]
                // 2. If no own override AND this cell has a mirror partner
                //    (only true for shared products in slow-ox buckets 1/2),
                //    fall back to the partner's override.
                if (v === undefined && isSlowOx) {
                  const mirror = mirrorPairs.find(
                    (m) => m.source[0] === bIdx && m.source[1] === pIdx
                  )
                  if (mirror) {
                    const [tBIdx, tPIdx] = mirror.target
                    // For NAK-driven products (zinc, na-k-up) the mirror
                    // partner uses the SAME slider-scoped override key, so
                    // we look it up via overrideKey(). Non-NAK products use
                    // a per-bucket doseKey() — the mirror falls back to that.
                    const mirrorKey = NAK_DRIVEN_PRODUCTS.has(p.id)
                      ? overrideKey(tBIdx, tPIdx, aIdx, p.id, nakRatio)
                      : doseKey(tBIdx, tPIdx, aIdx)
                    v = overrides[mirrorKey]
                  }
                }
                // 3. Na/K ratio dial (Luke 2026-09-09): for zinc-matrix-pro
                //    and na-k-up, the dose depends on the panel's Na/K
                //    ratio via the dose_schedule. Compute the adult dose at
                //    nakRatio, then run it through kids_dose to apply age
                //    scaling (and strip NOON for kids). This overrides the
                //    static `c` value when the slider has moved off 2.5.
                if (v === undefined && (p.id === 'zinc-matrix-pro' || p.id === 'na-k-up')) {
                  const sched = (p as ProductRowWithSchedule).dose_schedule
                  if (sched) {
                    const adultDose = linearInterpolateDose(sched.anchors, nakRatio)
                    // Kid scaling: apply age factor at the current age index.
                    // baseData.ages gives us the canonical age list since data
                    // isn't defined yet inside this useMemo closure.
                    const age = baseData.ages[aIdx]
                    const [kam, knoon, kpm] = kidsDose(
                      adultDose.am, adultDose.noon, adultDose.pm, age
                    )
                    v = `${kam}·${kpm}`
                  }
                }
                // 3.5. Adult override (Luke 2026-09-12): if the user
                //      edited the Adult column for this product in this
                //      bucket, re-derive the kid cell from the override
                //      using the same kidsDose() math that built the
                //      static `c` values. Applies to all non-NAK-driven
                //      products — the override IS the new adult source.
                //      For NAK-driven products the slider is the source
                //      of truth (step 3 above), so we skip them here.
                if (
                  v === undefined &&
                  p.id !== 'zinc-matrix-pro' &&
                  p.id !== 'na-k-up'
                ) {
                  const adultOverride = overrides[`adult-${bIdx}-${pIdx}`]
                  if (adultOverride !== undefined) {
                    const [aa, an, ap] = adultOverride.split('·')
                    const age = baseData.ages[aIdx]
                    const [kam, knoon, kpm] = kidsDose(aa ?? '0', an ?? '0', ap ?? '0', age)
                    v = `${kam}·${kpm}`
                  }
                }
                // 4. Fall back to auto-computed cell value
                return v ?? c
              })
            }
          })
        }
      })
    }
  }, [baseData, overrides, sdActive, nakRatio])

  if (!data) return <div className="loading">Loading matrix...</div>

  const bucketIdx = data.buckets.findIndex(b => b.name === activeBucket)
  const bucket = data.buckets[bucketIdx]
  const overrideCount = Object.keys(overrides).length

  // Handler for clicking a quick-dose chip
  const applyQuickDose = (bIdx: number, pIdx: number, aIdx: number, value: string, productId?: string) => {
    updateCell(bIdx, pIdx, aIdx, value, productId)
    // Keep focus on the input
    const key = doseKey(bIdx, pIdx, aIdx)
    setTimeout(() => inputsRef.current[key]?.focus(), 0)
  }

  return (
    <div className="app">
      <header className="header">
        <div className="header-row">
          <h1>HTMA Kids Matrix v2</h1>
          <div className="header-actions">
            <label className={`sd-toggle ${sdActive ? 'active' : ''}`} title="Sympathetic Dominance swap (slow-ox buckets only)">
              <input
                type="checkbox"
                checked={sdActive}
                onChange={(e) => setSdActive(e.target.checked)}
              />
              <span>SD (slow-ox only)</span>
            </label>
            <label className="nak-slider" title="Na/K ratio dial — drives zinc + na-k-up doses">
              <span className="nak-slider-label">Na/K</span>
              <input
                type="range"
                min={0.5}
                max={8.0}
                step={0.5}
                value={nakRatio}
                onChange={(e) => setNakRatio(parseFloat(e.target.value))}
              />
              <span className="nak-slider-value">{nakRatio.toFixed(1)}</span>
            </label>
            <button
              className={`btn btn-primary ${editMode ? 'active' : ''}`}
              onClick={() => setEditMode(!editMode)}
            >
              {editMode ? '✓ Editing' : 'Edit'}
            </button>
            <button className="btn" onClick={exportOverrides}>
              Export{overrideCount > 0 ? ` (${overrideCount})` : ''}
            </button>
            <button className="btn" onClick={importOverrides}>Import</button>
            <button className="btn btn-danger" onClick={resetAll} disabled={overrideCount === 0}>
              Reset
            </button>
          </div>
        </div>
        <p className="subtitle">
          Age-scaled doses for ages 1-18 · Strict 2x/day (AM + PM, NOON dropped for kids)
          · Cal-Mag Fusion gets 1.25× skew
        </p>
        {savedFlash && <div className="flash">Saved ✓</div>}
        {overrideCount > 0 && (
          <div className="override-banner">
            {overrideCount} manual override{overrideCount === 1 ? '' : 's'} applied.
            Edits persist to localStorage automatically.
          </div>
        )}
        <div className="legend">
          <span className="legend-item"><span className="swatch dose-zero" /> None</span>
          <span className="legend-item"><span className="swatch dose-quarter" /> ¼ each</span>
          <span className="legend-item"><span className="swatch dose-half" /> ⅓–½ each</span>
          <span className="legend-item"><span className="swatch dose-one" /> 1 each</span>
          <span className="legend-item"><span className="swatch dose-two" /> 2 each</span>
          <span className="legend-item"><span className="swatch dose-heavy" /> 3+ each</span>
        </div>
      </header>

      <nav className="bucket-nav">
        {data.buckets.map((b) => (
          <button
            key={b.name}
            className={`bucket-tab ${b.name === activeBucket ? 'active' : ''}`}
            onClick={() => setActiveBucket(b.name)}
          >
            {b.name}
          </button>
        ))}
      </nav>

      <main className="matrix">
        <h2 className="bucket-title">Bucket: {bucket.name}</h2>
        <div className="table-wrapper">
          <table className="matrix-table">
            <thead>
              <tr>
                <th className="product-col">Product</th>
                <th className="adult-col">Adult</th>
                {data.ages.map(a => (
                  <th key={a} className={`age-col ${a === 18 ? 'age-adult' : ''}`}>
                    {a}yo
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bucket.products.map((p, pIdx) => {
                // Adult override resolution: explicit override wins,
                // otherwise the slider-interpolated adult (for zinc /
                // na-k-up). Computed at the row level so both the Adult
                // <td> AND the cells.map below can see them — editing
                // the Adult re-derives every kid cell in the row.
                const adultOverride = overrides[`adult-${bucketIdx}-${pIdx}`]
                const adultDisplay = adultOverride ?? p.adult ?? '—'
                const adultHasOverride = adultOverride !== undefined
                return (
                <tr key={p.id} className={p.displayId ? 'sd-swap-row' : ''}>
                  <td className="product-cell">
                    <code>{p.displayId ?? p.id}</code>
                    {p.displayId && <span className="sd-swap-badge">SD</span>}
                    {p.gate && <span className="gate-badge">⌐{p.gate}</span>}
                  </td>
                  <td className={`adult-cell ${adultHasOverride ? 'has-override' : ''} ${editMode ? 'editable' : ''}`}>
                    {editMode ? (
                      <input
                        className="cell-input adult-input"
                        value={stripCap(adultDisplay)}
                        onChange={(e) => {
                          if (isValidDose(e.target.value)) {
                            const normalized = normalizeFractions(e.target.value)
                            updateAdultCell(bucketIdx, pIdx, normalized)
                          }
                        }}
                        placeholder="—"
                        autoComplete="off"
                        autoCorrect="off"
                        autoCapitalize="off"
                        spellCheck={false}
                      />
                    ) : (
                      stripCap(adultDisplay)
                    )}
                  </td>
                  {p.cells.map((c, aIdx) => {
                    const key = doseKey(bucketIdx, pIdx, aIdx)
                    const storageKey = overrideKey(bucketIdx, pIdx, aIdx, p.id, nakRatio)
                    const hasOverride = storageKey in overrides
                    // Cross-bucket shared override indicator: zinc and na-k-up
                    // overrides are shared across multiple buckets, so the
                    // orange border is more prominent for those.
                    const isSharedOverride = hasOverride && NAK_DRIVEN_PRODUCTS.has(p.id)
                    return (
                      <td
                        key={aIdx}
                        className={`dose-cell ${doseClass(c)} ${hasOverride ? 'has-override' : ''} ${isSharedOverride ? 'shared-override' : ''} ${editMode ? 'editable' : ''} ${activeCellKey === key ? 'cell-active' : ''}`}
                      >
                        {editMode ? (
                          <div className="cell-editor">
                            <input
                              id={`cell-${key}`}
                              ref={(el) => {
                                inputsRef.current[key] = el
                                // No DOM sync here. The input is controlled
                                // by React via value={c}; React updates the
                                // DOM when c changes. We don't manually set
                                // el.value because that would clobber the
                                // user's input during typing.
                              }}
                              className="cell-input"
                              value={c}
                              onChange={(e) => {
                                if (isValidDose(e.target.value)) {
                                  const normalized = normalizeFractions(e.target.value)
                                  updateCell(bucketIdx, pIdx, aIdx, normalized, p.id)
                                }
                              }}
                              onFocus={() => {
                                setActiveCellKey(key)
                                setPickerHost(key)
                              }}
                              onBlur={() => {
                                // Don't reset DOM value to state on blur.
                                // onChange already committed the user's typing.
                                // Delay picker hide so click on chip can fire first
                                setTimeout(() => {
                                  setActiveCellKey((prev) => prev === key ? null : prev)
                                  setPickerHost((prev) => prev === key ? null : prev)
                                }, 150)
                              }}
                              placeholder="—"
                              autoComplete="off"
                              autoCorrect="off"
                              autoCapitalize="off"
                              spellCheck={false}
                            />
                            {/* Picker rendered via portal so it doesn't interfere with typing */}
                            {activeCellKey === key && pickerHost === key && createPortal(
                              <div className="dose-picker" onMouseDown={(e) => e.preventDefault()}>
                                {QUICK_DOSES.map(qd => (
                                  <button
                                    key={qd}
                                    className="dose-chip"
                                    onClick={() => applyQuickDose(bucketIdx, pIdx, aIdx, qd, p.id)}
                                    type="button"
                                    tabIndex={-1}
                                  >
                                    {qd}
                                  </button>
                                ))}
                              </div>,
                              document.body
                            )}
                          </div>
                        ) : (
                          <span>{c}</span>
                        )}
                      </td>
                    )
                  })}
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </main>

      <footer className="footer">
        <p>
          Rules: ≤18 → strict 2x/day · Age anchors: 0→0.0, 6→0.5, 12→0.75, 18→1.0
          · Cal-Mag 1.25× skew · Age gates: AdrenoFuel ≥9, ThyroSpark ≥5
        </p>
        <p className="footer-hint">
          {editMode
            ? 'Click any cell to focus it. Use the dose chips below the input for quick fractions (¼, ⅓, ½, ⅔, ¾, 1, 1½, 2...). Type custom values too. Edits save to localStorage automatically.'
            : 'Click "Edit" to override doses. Cells with manual edits show an orange highlight.'}
        </p>
      </footer>
    </div>
  )
}

export default App
