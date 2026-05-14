---
name: shadcn-vue-tailwind-frontend
description: Build production-grade frontends with Vue 3, shadcn-vue, and Tailwind CSS v4. Use this skill when creating or refactoring pages, dashboards, forms, result views, navigators, status-heavy interfaces, or app shells in a shadcn-vue stack, especially when the user wants strong information hierarchy, polished motion, Zinc-based theming, reusable component structure, and TypeScript-first Vue architecture.
metadata:
  author: Max
  stack: vue3-shadcn-vue-tailwind-v4
---

# Shadcn Vue Tailwind Frontend

Build interfaces that feel deliberate, clean, and production-ready rather than generic. Favor strong structure, careful spacing, restrained color, and component reuse.

## Workflow

1. Identify the product surface before coding.
   Determine the main route structure, page goals, primary user actions, async states, and whether the UI is form-first, navigation-first, or result-first.

2. Use the stack consistently.
   Build with Vue 3 Composition API, `<script setup>`, TypeScript types for props and API responses, shadcn-vue components from `src/components/ui/`, Tailwind CSS v4 utilities, and Pinia for cross-view state when the interaction spans routes or async workflows.

3. Establish the shell and information hierarchy first.
   Start with app frame, header, primary panels, sticky regions, navigators, and result areas before polishing leaf components. Make layout decisions obvious on desktop and mobile.

4. Prefer composition over one-off pages.
   Split work into route views, domain components, layout components, and small status/presentation components. Repeated UI patterns such as badges, status rows, metadata labels, timing displays, and tabbed panels should become reusable components.

5. Design tokens come before ad hoc color choices.
   Use a Zinc-centered light/dark theme with CSS variables and Tailwind v4 `@theme inline`. Keep background, foreground, border, primary, muted, success, warning, and destructive values centralized.

6. Encode async UX deliberately.
   For submit, loading, polling, empty, success, error, and cached states, provide explicit UI treatment. Use skeletons, progress indicators, toasts, and status messaging rather than leaving blank regions.

7. Use motion with purpose.
   Add small transitions for page entry, status changes, active navigation, and reveal states. Avoid decorative motion that competes with information density.

8. Preserve implementation quality.
   Keep logic typed, stores focused, components narrow in responsibility, and class usage readable. If a component becomes hard to scan, extract subcomponents or computed state.

## Design Rules

### Visual direction

- Use a restrained Zinc palette with blue as the primary interactive color.
- Keep cards light and readable in both themes.
- Use borders and subtle background shifts more often than heavy shadows.
- Avoid purple-biased defaults, generic gradients, and random accent colors.

### Typography

- Use `Geist Sans` for body, labels, and headings.
- Use `Geist Mono` for identifiers, accession numbers, CIKs, URLs, and machine-like values.
- Use larger, editorial heading treatment only when the page has a clear hero moment.

### Interaction

- Active navigation should be immediately legible through border, tint, and text emphasis.
- Hover states should feel responsive but restrained.
- Focus states must remain visible with ring treatment; never rely on browser outline alone.
- Disabled and unavailable states should be obviously non-interactive.

### Components

- Prefer shadcn-vue primitives such as `Button`, `Input`, `Tabs`, `Card`, `Badge`, `Separator`, `Skeleton`, `ScrollArea`, `Tooltip`, `Toast`, and `Toaster`.
- Use `lucide-vue-next` for icons.
- Prefer utility classes over large scoped CSS blocks unless the styling is genuinely structural or reusable.

## Architecture Rules

- Put route views in `src/views/`.
- Put shared layout in `src/components/layout/`.
- Put page-specific domain components in folders such as `home/`, `result/`, or the relevant feature area.
- Put API clients in `src/lib/`.
- Put request and response types in `src/types/`.
- Put app-level state in focused Pinia stores under `src/stores/`.

## Tailwind v4 Rules

- Define tokens in CSS using `@theme inline`; do not depend on legacy `tailwind.config.js` theming when CSS-first configuration is sufficient.
- Use `.dark` class switching for theme mode.
- Keep token naming aligned with shadcn-vue expectations: background, foreground, card, border, input, primary, primary-foreground, destructive, plus any project-specific success or warning colors.
- Favor utility classes and `tw-animate-css` utilities before custom keyframes.

## State and Async Patterns

- Use a route-aware store for long-running jobs, polling, and result hydration.
- Keep navigator state separate from job state when the user can browse extracted sections independently of fetching.
- Cache derived or secondary fetches only when they are scoped cleanly by stable keys.
- Reset intervals, timers, and abortable requests on unmount or route changes.

## Output Expectations

Produce:

- clear route structure
- reusable Vue components
- typed stores and API boundaries
- responsive layout behavior
- explicit loading, success, error, and empty states
- polished but restrained visual design

Do not produce:

- monolithic page components when the UI has clear subdomains
- arbitrary color systems disconnected from Zinc tokens
- Tailwind plus large conflicting scoped CSS overrides
- vague placeholder async behavior
- inconsistent typography for identifiers versus prose
