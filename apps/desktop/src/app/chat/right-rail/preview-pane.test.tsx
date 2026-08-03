import { act, cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $connection } from '@/store/session'

import { PreviewPane } from './preview-pane'
import { forgetPreviewStripTools, previewConsoleState } from './preview-strip-tools'

describe('PreviewPane console state', () => {
  beforeEach(() => {
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) =>
      window.setTimeout(() => callback(Date.now()), 0)
    )
    vi.stubGlobal('cancelAnimationFrame', (id: number) => window.clearTimeout(id))
  })

  afterEach(() => {
    cleanup()
    $connection.set(null)
    vi.unstubAllGlobals()
  })

  it('does not watch backend-only remote filesystem previews locally', async () => {
    const watchPreviewFile = vi.fn(async () => ({ id: 'watch-1', path: '/remote/file.txt' }))
    const onPreviewFileChanged = vi.fn(() => vi.fn())
    $connection.set({ mode: 'remote' } as never)
    vi.stubGlobal('window', {
      ...window,
      hermesDesktop: {
        onPreviewFileChanged,
        watchPreviewFile
      }
    })

    await act(async () => {
      render(
        <PreviewPane
          target={{
            kind: 'file',
            label: 'file.txt',
            path: '/remote/file.txt',
            previewKind: 'text',
            source: '/remote/file.txt',
            url: 'file:///remote/file.txt'
          }}
        />
      )
    })

    expect(watchPreviewFile).not.toHaveBeenCalled()
    expect(onPreviewFileChanged).not.toHaveBeenCalled()
  })

  // The console lives in the TAB's store (the toggles sit on the tab, not in the
  // titlebar), so a streamed log has to land in the store keyed by tabId — that
  // is what both the panel in the pane and the button on the tab read.
  it('streams console logs into the tab-keyed console store', async () => {
    const tabId = 'url:http://localhost:5174'

    forgetPreviewStripTools(tabId)

    let rendered!: ReturnType<typeof render>
    await act(async () => {
      rendered = render(
        <PreviewPane
          tabId={tabId}
          target={{
            kind: 'url',
            label: 'Preview',
            source: 'http://localhost:5174',
            url: 'http://localhost:5174'
          }}
        />
      )
    })

    const webview = rendered.container.querySelector('webview')

    expect(webview).toBeInstanceOf(HTMLElement)

    act(() => {
      webview?.dispatchEvent(
        Object.assign(new Event('console-message'), {
          level: 0,
          message: 'streamed log line',
          sourceId: 'http://localhost:5174/src/main.tsx'
        })
      )
    })

    expect(previewConsoleState(tabId).$logs.get().at(-1)?.message).toBe('streamed log line')

    forgetPreviewStripTools(tabId)
  })
})
