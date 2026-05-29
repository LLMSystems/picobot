<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { basicSetup, EditorView } from 'codemirror'
import { Compartment, EditorState, type Extension } from '@codemirror/state'
import { keymap } from '@codemirror/view'
import { indentWithTab } from '@codemirror/commands'

import { python } from '@codemirror/lang-python'
import { javascript } from '@codemirror/lang-javascript'
import { html } from '@codemirror/lang-html'
import { css } from '@codemirror/lang-css'
import { json } from '@codemirror/lang-json'
import { yaml } from '@codemirror/lang-yaml'
import { markdown } from '@codemirror/lang-markdown'
import { xml } from '@codemirror/lang-xml'
import { rust } from '@codemirror/lang-rust'
import { go } from '@codemirror/lang-go'
import { java } from '@codemirror/lang-java'
import { cpp } from '@codemirror/lang-cpp'
import { php } from '@codemirror/lang-php'
import { sql } from '@codemirror/lang-sql'
import { vue as vueLang } from '@codemirror/lang-vue'

import type { CodeFontSize } from '@/composables/useCodePreviewPrefs'

const props = withDefaults(
  defineProps<{
    modelValue: string
    editable?: boolean
    language?: string | null
    wrap?: boolean
    fontSize?: CodeFontSize
    onSave?: () => void
  }>(),
  {
    editable: false,
    language: null,
    wrap: false,
    fontSize: 'sm',
    onSave: undefined,
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const hostEl = ref<HTMLElement | null>(null)
const view = shallowRef<EditorView | null>(null)

const langCompartment = new Compartment()
const wrapCompartment = new Compartment()
const sizeCompartment = new Compartment()
const editableCompartment = new Compartment()
const readOnlyCompartment = new Compartment()

let internalSet = false

function langExtension(name: string | null | undefined): Extension {
  switch (name) {
    case 'python':
      return python()
    case 'javascript':
      return javascript({ jsx: true })
    case 'typescript':
      return javascript({ jsx: true, typescript: true })
    case 'xml':
      return xml()
    case 'html':
      return html()
    case 'css':
      return css()
    case 'json':
      return json()
    case 'yaml':
      return yaml()
    case 'markdown':
      return markdown()
    case 'rust':
      return rust()
    case 'go':
      return go()
    case 'java':
      return java()
    case 'cpp':
    case 'c':
      return cpp()
    case 'php':
      return php()
    case 'sql':
      return sql()
    case 'vue':
      return vueLang()
    default:
      return []
  }
}

function sizeExtension(size: CodeFontSize): Extension {
  const px = size === 'lg' ? 14 : size === 'md' ? 13 : 12
  return EditorView.theme({
    '&': { fontSize: `${px}px` },
  })
}

const baseTheme = EditorView.theme({
  '&': {
    height: '100%',
    backgroundColor: 'transparent',
    color: 'var(--foreground)',
  },
  '.cm-scroller': {
    fontFamily:
      'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
    lineHeight: '1.55',
  },
  '.cm-content': {
    caretColor: 'var(--foreground)',
    padding: '12px 0',
  },
  '.cm-gutters': {
    backgroundColor: 'transparent',
    color: 'color-mix(in oklch, var(--muted-foreground) 70%, transparent)',
    borderRight: '1px solid var(--border)',
  },
  '.cm-activeLine': { backgroundColor: 'transparent' },
  '.cm-activeLineGutter': { backgroundColor: 'transparent' },
  '&.cm-focused .cm-activeLine': {
    backgroundColor:
      'color-mix(in oklch, var(--muted) 50%, transparent)',
  },
  '&.cm-focused .cm-activeLineGutter': {
    backgroundColor:
      'color-mix(in oklch, var(--muted) 50%, transparent)',
    color: 'var(--foreground)',
  },
  '.cm-selectionBackground, ::selection': {
    backgroundColor:
      'color-mix(in oklch, var(--primary) 25%, transparent) !important',
  },
  '&.cm-focused .cm-selectionBackground': {
    backgroundColor:
      'color-mix(in oklch, var(--primary) 35%, transparent) !important',
  },
  '.cm-cursor, .cm-dropCursor': {
    borderLeftColor: 'var(--foreground)',
  },
  '.cm-panels': {
    backgroundColor: 'var(--background)',
    color: 'var(--foreground)',
    borderTop: '1px solid var(--border)',
  },
  '.cm-panels.cm-panels-top': { borderBottom: '1px solid var(--border)' },
  '.cm-tooltip': {
    backgroundColor: 'var(--popover)',
    color: 'var(--popover-foreground)',
    border: '1px solid var(--border)',
  },
  '.cm-searchMatch': {
    backgroundColor:
      'color-mix(in oklch, var(--primary) 25%, transparent)',
  },
  '.cm-searchMatch.cm-searchMatch-selected': {
    backgroundColor:
      'color-mix(in oklch, var(--primary) 50%, transparent)',
  },
})

onMounted(() => {
  if (!hostEl.value) return
  const editable = props.editable
  const extensions: Extension[] = [
    basicSetup,
    baseTheme,
    keymap.of([
      indentWithTab,
      {
        key: 'Mod-s',
        preventDefault: true,
        run: () => {
          props.onSave?.()
          return true
        },
      },
    ]),
    EditorView.updateListener.of((u) => {
      if (u.docChanged && !internalSet) {
        emit('update:modelValue', u.state.doc.toString())
      }
    }),
    langCompartment.of(langExtension(props.language)),
    wrapCompartment.of(props.wrap ? EditorView.lineWrapping : []),
    sizeCompartment.of(sizeExtension(props.fontSize)),
    editableCompartment.of(EditorView.editable.of(editable)),
    readOnlyCompartment.of(EditorState.readOnly.of(!editable)),
  ]
  const state = EditorState.create({
    doc: props.modelValue,
    extensions,
  })
  view.value = new EditorView({ state, parent: hostEl.value })
})

onBeforeUnmount(() => {
  view.value?.destroy()
  view.value = null
})

watch(
  () => props.modelValue,
  (val) => {
    const v = view.value
    if (!v) return
    if (v.state.doc.toString() === val) return
    internalSet = true
    v.dispatch({
      changes: { from: 0, to: v.state.doc.length, insert: val },
    })
    internalSet = false
  },
)

watch(
  () => props.language,
  (lang) => {
    view.value?.dispatch({
      effects: langCompartment.reconfigure(langExtension(lang)),
    })
  },
)

watch(
  () => props.wrap,
  (w) => {
    view.value?.dispatch({
      effects: wrapCompartment.reconfigure(w ? EditorView.lineWrapping : []),
    })
  },
)

watch(
  () => props.fontSize,
  (s) => {
    view.value?.dispatch({
      effects: sizeCompartment.reconfigure(sizeExtension(s)),
    })
  },
)

watch(
  () => props.editable,
  (e) => {
    view.value?.dispatch({
      effects: [
        editableCompartment.reconfigure(EditorView.editable.of(e)),
        readOnlyCompartment.reconfigure(EditorState.readOnly.of(!e)),
      ],
    })
  },
)
</script>

<template>
  <div ref="hostEl" class="h-full min-h-0 w-full overflow-hidden" />
</template>
