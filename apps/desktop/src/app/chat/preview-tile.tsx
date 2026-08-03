/**
 * PREVIEW TILES — every open preview (a file, a URL, an artifact) rendered as a
 * layout-tree pane, the preview analog of session and route tiles.
 *
 * The rail used to bring its OWN tab strip: a second bar beside the zone's own,
 * at a different height, with its own close menu and its own label casing. It
 * predated the layout tree. Now `$previewTabs` mirrors into pane contributions
 * through the same `paneMirror` the other tiles use, so a preview tab IS a zone
 * tab — same strip, same drag/stack/split, same ⌘W, same right-click verbs, and
 * one bar instead of two.
 */

import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { ToolIcon } from '@/components/ui/tool-icon'
import { $previewTabs, closeRightRailTab, type PreviewTarget } from '@/store/preview'

import { paneMirror } from './pane-mirror'
import { PreviewTilePane } from './right-rail/preview'
import { forgetPreviewStripTools, previewStripTools } from './right-rail/preview-strip-tools'

/** The target behind a tile id, or null once its tab is gone. */
function targetFor(tabId: string): PreviewTarget | null {
  return $previewTabs.get().find(tab => tab.id === tabId)?.target ?? null
}

/** Tab title. A URL is a BROWSER — the tab names the surface, not the page, so
 *  it doesn't rename itself on every navigation. A file names the file; an
 *  artifact is titled rather than located, so its label is the whole name. */
function previewTitle(tabId: string): string {
  const target = targetFor(tabId)

  if (!target) {
    return 'Preview'
  }

  if (target.kind === 'url') {
    return 'Browser'
  }

  if (target.kind === 'artifact') {
    return target.label || 'Preview'
  }

  const value = target.label || target.path || target.source || target.url
  const tail = value.split(/[\\/]/).filter(Boolean).at(-1)

  return tail || value || 'Preview'
}

/** The tab's lead glyph — the same file/tool icon family the file tree and code
 *  fences resolve through, so a `.tsx` peek and its sidebar row agree. */
function PreviewTabLead({ tabId }: { tabId: string }) {
  const target = targetFor(tabId)

  if (!target) {
    return null
  }

  if (target.kind === 'artifact') {
    return <ToolIcon className="opacity-70" name="sparkle" size="0.6875rem" />
  }

  if (target.kind === 'url') {
    return <ToolIcon className="opacity-70" name="globe" size="0.6875rem" />
  }

  return <FileTypeIcon className="opacity-70" path={target.path || target.url} size="0.6875rem" />
}

const PREVIEW_TILE_PREFIX = 'preview-tile'

/** Keep pane contributions mirroring `$previewTabs`. Call once from the root. */
export const watchPreviewTiles = paneMirror<{ id: string }>({
  source: $previewTabs,
  key: tab => tab.id,
  prefix: PREVIEW_TILE_PREFIX,
  // Identical to route (page) tiles: its own zone docked beside main, sized by
  // the split weights. NOT anchored to the file tree — the old rail was a
  // files-adjacent strip, and carrying that over welded preview into the file
  // browser's zone, so ⌘J (toggle file browser) took the preview with it.
  dir: () => 'right',
  minWidth: '22rem',
  title: previewTitle,
  tabLead: tabId => <PreviewTabLead tabId={tabId} />,
  // Console + DevTools as bare strip glyphs after the last tab, where "+" sits.
  // Only a URL preview has a webview behind it, so a file/artifact tab gets none.
  stripTools: tabId => (targetFor(tabId)?.kind === 'url' ? previewStripTools(tabId) : []),
  render: tabId => <PreviewTilePane tabId={tabId} />,
  close: tabId => {
    forgetPreviewStripTools(tabId)
    closeRightRailTab(tabId)
  }
})
