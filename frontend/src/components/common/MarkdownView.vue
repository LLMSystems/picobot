<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '@/lib/markdown'

const props = defineProps<{ content: string }>()

const html = computed(() => renderMarkdown(props.content))
</script>

<template>
  <div class="markdown-body text-sm leading-relaxed" v-html="html" />
</template>

<style>
.markdown-body p {
  margin: 0 0 0.75em;
}
.markdown-body p:last-child {
  margin-bottom: 0;
}
.markdown-body ul,
.markdown-body ol {
  margin: 0 0 0.75em;
  padding-left: 1.25em;
}
.markdown-body ul {
  list-style: disc;
}
.markdown-body ol {
  list-style: decimal;
}
.markdown-body li {
  margin: 0.15em 0;
}
.markdown-body h1,
.markdown-body h2,
.markdown-body h3,
.markdown-body h4 {
  font-weight: 600;
  margin: 1em 0 0.5em;
  line-height: 1.3;
}
.markdown-body h1 {
  font-size: 1.4em;
}
.markdown-body h2 {
  font-size: 1.25em;
}
.markdown-body h3 {
  font-size: 1.1em;
}
.markdown-body code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  background: var(--muted);
  padding: 0.1em 0.35em;
  border-radius: 4px;
  font-size: 0.85em;
}
.markdown-body pre {
  background: var(--muted);
  border-radius: 8px;
  padding: 0.75em 1em;
  overflow-x: auto;
  margin: 0 0 0.75em;
  font-size: 0.85em;
  line-height: 1.5;
}
.markdown-body pre code,
.markdown-body pre code.hljs {
  background: transparent;
  padding: 0;
  font-size: 1em;
  color: inherit;
  display: block;
}
.markdown-body a {
  color: var(--primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.markdown-body blockquote {
  border-left: 3px solid var(--border);
  padding-left: 0.75em;
  margin: 0 0 0.75em;
  color: var(--muted-foreground);
}
.markdown-body table {
  border-collapse: collapse;
  margin: 0 0 0.75em;
  font-size: 0.9em;
}
.markdown-body th,
.markdown-body td {
  border: 1px solid var(--border);
  padding: 0.35em 0.6em;
}
.markdown-body hr {
  border: 0;
  border-top: 1px solid var(--border);
  margin: 1em 0;
}
</style>
