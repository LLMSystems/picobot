// Maps backend agent type names to their picobot persona artwork.
// The backend /agent-types only returns name/display_name/description, so the
// icon association lives here. Unknown types fall back to the default persona.
import defaultIcon from '@/assets/picobots/picobot.png'
import coderIcon from '@/assets/picobots/picobot4_rem.png'
import researcherIcon from '@/assets/picobots/picobot3_rem.png'
import analystIcon from '@/assets/picobots/picobot2_rem.png'

const PERSONA_ICONS: Record<string, string> = {
  default: defaultIcon,
  coder: coderIcon,
  researcher: researcherIcon,
  analyst: analystIcon,
}

export function personaIcon(name: string | null | undefined): string {
  if (name && PERSONA_ICONS[name]) return PERSONA_ICONS[name]
  return defaultIcon
}
