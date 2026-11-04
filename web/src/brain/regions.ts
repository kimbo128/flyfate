// Functional groups of the MaleCNS ROIs (colour, decision type), plain names and explanations per ROI, and
// plain words for cell-type families. The data lives in public/brain/legend.json, which the server's share
// cards and pages read too.
import legend from '../../public/brain/legend.json'

export type Kind = { id: string; title: string; line: string }

export type Group = {
  id: string
  name: string
  rois: string[]
  color: string
  kind: Kind
  about: string
}

export const GROUPS: Group[] = legend.groups
const ROI_NAMES: Record<string, string> = legend.roi_names
const ROIS: Record<string, { plain: string; about: string }> = legend.rois
// Longest prefix first, so 'KCg' wins over 'KC'.
const CELLS = [...legend.cells].sort((a, b) => b[0].length - a[0].length)

export const baseRoi = (name: string) => name.replace(/\((L|R)\)$/, '')

export function groupOf(roi: string): Group {
  const base = baseRoi(roi)
  return GROUPS.find((g) => g.rois.includes(base)) ?? GROUPS[GROUPS.length - 1]
}

// "gL(R)" -> "Mushroom body γ lobe, right"
export function roiLabel(roi: string) {
  const side = roi.match(/\((L|R)\)$/)?.[1]
  const name = ROI_NAMES[baseRoi(roi)] ?? baseRoi(roi)
  return side ? `${name}, ${side === 'L' ? 'left' : 'right'}` : name
}

// "gL(R)" -> "Short-term memory lobe"
export const plainName = (roi: string) => ROIS[baseRoi(roi)]?.plain ?? roiLabel(roi)

// What the region does, in one sentence; its brain system's description when there is none of its own.
export const aboutRoi = (roi: string) => ROIS[baseRoi(roi)]?.about ?? groupOf(roi).about

// "KCg-m" -> "Kenyon cells, the memory centre's short-term keepers"
export const cellFamily = (type: string) => CELLS.find(([prefix]) => type.startsWith(prefix))?.[1]
