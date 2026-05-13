import MarkdownIt from 'markdown-it'
import hljsPlugin from 'markdown-it-highlightjs'
import hljs from 'highlight.js'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github-dark.css'

const md = new MarkdownIt({
  linkify: true,
  breaks: true,
  html: false,
}).use(hljsPlugin, { auto: true, code: true, inline: false })

const hljsFence = md.renderer.rules.fence!
md.renderer.rules.fence = function (tokens, idx, options, env, self) {
  const token = tokens[idx]
  if (!token) return ''
  const info = token.info.trim().split(/\s+/)[0] ?? ''
  if (info === 'mermaid' || (info && !hljs.getLanguage(info))) {
    const langClass = info ? ` class="language-${info}"` : ''
    return `<pre><code${langClass}>${md.utils.escapeHtml(token.content)}</code></pre>\n`
  }
  return hljsFence(tokens, idx, options, env, self)
}

const defaultLinkOpen =
  md.renderer.rules.link_open ??
  function (tokens, idx, options, _env, self) {
    return self.renderToken(tokens, idx, options)
  }

md.renderer.rules.link_open = function (tokens, idx, options, env, self) {
  const token = tokens[idx]
  if (token) {
    const aIndex = token.attrIndex('target')
    if (aIndex < 0) token.attrPush(['target', '_blank'])
    else token.attrs![aIndex]![1] = '_blank'

    const rIndex = token.attrIndex('rel')
    if (rIndex < 0) token.attrPush(['rel', 'noopener noreferrer'])
    else token.attrs![rIndex]![1] = 'noopener noreferrer'
  }
  return defaultLinkOpen(tokens, idx, options, env, self)
}

export function renderMarkdown(source: string): string {
  if (!source) return ''
  const html = md.render(source)
  return DOMPurify.sanitize(html, {
    ADD_ATTR: ['target', 'rel'],
  })
}
