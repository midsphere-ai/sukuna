# Computer Panel Components — Rendering Specification

This document catalogs all MCP tool result types from the sandbox agent server and specifies the rendering strategy for the computer panel UI.

## Panel Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Header: "[agent]'s computer" · VNC toggle · Tool nav    │
├─────────────────────────────────────────────────────────┤
│ Tool Slider: ◀ [Tool 3 of 12] ▶                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Content Area (rendered by tool type):                  │
│  - TerminalRenderer                                     │
│  - CodeRenderer / DiffRenderer                          │
│  - BrowserRenderer (screenshots / VNC)                  │
│  - SearchResultsRenderer                                │
│  - ImageGalleryRenderer                                 │
│  - FileTreeRenderer                                     │
│  - DataTableRenderer                                    │
│  - MediaPlayer (audio/video)                            │
│  - MarkdownRenderer (fallback for text results)         │
│  - GenericJsonRenderer (unknown tools)                  │
│                                                         │
├─────────────────────────────────────────────────────────┤
│ Plan Overview (expandable): Phase 2 of 4 — "Building"  │
└─────────────────────────────────────────────────────────┘
```

### Layout

- **Desktop**: Right of chat, resizable via drag handle, collapsible via `Ctrl+Shift+C`
- **Mobile**: Bottom drawer with peek/half/full states and swipe gestures

### Tab Auto-Switching

The panel auto-switches to show the latest tool result unless the user has pinned a specific view. The `TOOL_TAB_MAP` maps tool server categories to panel content types:

| Server Category | Panel Content | Auto-switch Trigger |
|----------------|---------------|---------------------|
| terminal       | TerminalRenderer | `mcp_run_shell_command`, `mcp_run_python_code` |
| code           | CodeRenderer | `mcp_run_python_code` (code tab variant) |
| file           | CodeRenderer / DiffRenderer / FileTreeRenderer | `edit_file`, `read_file`, `list_directory` |
| browser        | BrowserRenderer | `mcp_use_browser`, `mcp_screenshot_url` |
| search         | SearchResultsRenderer | `mcp_search_google`, `mcp_search_google_images` |
| media          | ImageGalleryRenderer / MediaPlayer | `mcp_create_genai_image`, `mcp_create_genai_video` |
| audio          | MediaPlayer (audio) | `mcp_text_to_speech`, `mcp_audio_transcription` |
| vision         | MarkdownRenderer | `mcp_visual_question_answering` |
| web            | DataTableRenderer / StatusCard | `mcp_query_database`, `mcp_start_dev_server` |
| slides         | StatusCard | `mcp_create_presentation` |
| download       | StatusCard | `mcp_download_file` |
| plan           | PlanOverview (existing) | `mcp_update_plan`, `mcp_advance_plan` |
| reasoning      | MarkdownRenderer | `mcp_reason_about_problem` |
| reading        | MarkdownRenderer | `mcp_read_resource_file` |
| unknown        | GenericJsonRenderer | Any unrecognized tool |

### Pin Behavior

- User clicks pin icon → `tabPinned = true` → panel stays on current tool
- New tool results still update the tool slider counter but don't change displayed content
- Unpin reverts to auto-switching

---

## Core Response Structure

All agent server tools return a standardized shape:

```typescript
interface ToolResult {
  success: boolean;
  message: string;       // Human-readable summary
  error?: string;        // Error description (on failure)
  hint?: string;         // Actionable suggestion (on failure)
  // ... tool-specific fields below
}
```

---

## Tool Result Types by Renderer

### 1. TerminalRenderer

**Renders:** Shell command and Python code execution output.

**Tools:**
- `mcp_run_shell_command` (server: code)
- `mcp_run_python_code` (server: code)

**Result Shape:**
```typescript
interface TerminalResult extends ToolResult {
  exit_code: number;
  stdout: string;
  stderr: string;
  package_install_note?: string;  // shell only
  pid?: number;                   // background process only
}
```

**Rendering Spec:**
- Dark background (#1e1e1e) with monospace font
- ANSI color code support (convert to CSS)
- stdout in white, stderr in red/orange
- Exit code badge: green `0`, red non-zero
- Command shown at top: `$ {command}`
- Scrollable with max-height, auto-scroll to bottom
- Copy button in header
- If `pid` present, show "Background process PID: {pid}" badge

---

### 2. CodeRenderer

**Renders:** File content with syntax highlighting.

**Tools:**
- `read_file` (server: file) — file content
- `read_reference_file` (server: file) — reference file content
- `mcp_read_resource_file` (server: reading) — document content (markdown)

**Result Shape (read_file):**
```typescript
// result is a plain string (file content)
type ReadFileResult = string;
```

**Rendering Spec:**
- Syntax highlighting via language detection from file extension in args (`path` or `file_path`)
- Line numbers
- Copy and download buttons
- File path shown in header
- Max-height with scroll, expandable to full height

---

### 3. DiffRenderer

**Renders:** File edit diffs with color-coded changes.

**Tools:**
- `edit_file` (server: file)

**Result Shape:**
```typescript
interface DiffResult extends ToolResult {
  diff: string;          // Unified diff format
  match_results: Array<{
    edit_index: number;
    match_type: 'exact' | 'fuzzy' | 'failed';
    details: string;
  }>;
  file_path: string;
  dry_run: boolean;
}
```

**Rendering Spec:**
- Split or unified diff view (user toggle)
- Green for additions (`+`), red for deletions (`-`), gray for context
- Line numbers on both sides (split view)
- File path in header
- Match quality indicators: green "exact", yellow "fuzzy", red "failed"
- "Dry run" badge if `dry_run: true`
- Collapsed by default for large diffs (>50 lines), expand button

---

### 4. FileTreeRenderer

**Renders:** Directory listings as an interactive tree.

**Tools:**
- `list_directory` (server: file)
- `list_reference_directory` (server: file)

**Result Shape:**
```typescript
// result is a string[] (file/directory paths)
type DirectoryResult = string[];
```

**Rendering Spec:**
- Tree structure with folder/file icons
- Folders first, sorted alphabetically
- Indent by depth
- File type icons based on extension
- Click to request `read_file` (future interaction)
- Collapsible directories

---

### 5. BrowserRenderer

**Renders:** Browser automation progress with screenshots, and live VNC desktop view.

**Tools:**
- `mcp_use_browser` (server: search) — progress updates with screenshots
- `mcp_screenshot_url` (server: search) — static screenshot
- `mcp_scrape_url` (server: search) — webpage content

**mcp_use_browser Progress Updates:**

The `mcp_use_browser` tool emits MCP progress notifications during execution. These arrive as `mcp_progress` SSE events with incremental data:

```typescript
interface BrowserProgressUpdate {
  step: number;
  status: 'starting' | 'completed' | 'failed' | 'error';
  task: string;
  cdp_url: string;
  url?: string;         // Current page URL
  screenshot?: string;  // Base64-encoded PNG
}
```

**Rendering Spec:**
- **During execution:** Progress bar (step N of M), current task description, live screenshot updates
- **Screenshot display:** Full-width image, auto-updates as new screenshots arrive
- **Step history:** Carousel of previous screenshots with step descriptions
- **Final result:** Full content rendered as markdown (from the tool result `message`)
- **mcp_screenshot_url:** Single static screenshot image
- **mcp_scrape_url:** Rendered markdown content viewer

**VNC Desktop Streaming:**
- Toggle button in panel header switches between tool results and live VNC
- VNC URL format: `https://{sandbox_host}/vnc?auth_key={key}`
- Embed via `<iframe>` pointing to sandbox stream URL
- Only one stream active at a time
- Loading state while connecting, error state if sandbox unavailable

**VNC Lifecycle:**
1. Frontend requests VNC start from backend → `sandbox.stream.start(require_auth=True)`
2. Backend returns `{ stream_url, auth_key }`
3. Frontend embeds `<iframe src="{stream_url}" />`
4. On toggle off → `sandbox.stream.stop()`

---

### 6. SearchResultsRenderer

**Renders:** Google search results and image search results.

**Tools:**
- `mcp_search_google` (server: search)
- `mcp_search_google_images` (server: search)
- `mcp_search_wikipedia`, `mcp_get_wikipedia_article`, `mcp_get_wikipedia_summary` (server: search)

**Search Result Shape:**
```typescript
interface SearchResult extends ToolResult {
  query: string;
  results: Array<{
    id: string;
    title: string;
    url: string;
    snippet: string;
    source: string;
    display_link: string;
    formatted_url: string;
  }>;
  count: number;
}
```

**Image Search Result Shape:**
```typescript
interface ImageSearchResult extends ToolResult {
  query: string;
  results: Array<{
    id: string;
    title: string;
    url: string;
    snippet: string;
    image_path: string;  // Local path in sandbox
    source: string;
    display_link: string;
  }>;
  count: number;
}
```

**Rendering Spec:**
- **Web search:** Card list with title (clickable link), snippet, source domain
- **Image search:** Grid gallery with thumbnails, title overlays, lightbox on click
- **Wikipedia:** Markdown content viewer
- Query shown in header
- Result count badge

---

### 7. ImageGalleryRenderer

**Renders:** Generated images, screenshots, and keyframes.

**Tools:**
- `mcp_create_genai_image` (server: media)
- `mcp_create_genai_image_with_references` (server: media)
- `mcp_edit_genai_image` (server: media)
- `mcp_extract_keyframes` (server: vision)
- `mcp_search_google_images` (server: search) — also uses SearchResultsRenderer

**Result Shape:**
```typescript
interface ImageResult extends ToolResult {
  file_path: string;    // Path in sandbox filesystem
}
```

**Rendering Spec:**
- Full-width image display
- Lightbox on click (zoom, pan)
- Download button
- For `mcp_edit_genai_image`: before/after comparison slider
- For `mcp_extract_keyframes`: Grid of thumbnail images with timestamps
- Image files accessed via sandbox file API: `GET /uploads/{path}`

---

### 8. MediaPlayer

**Renders:** Audio and video content.

**Tools:**
- `mcp_text_to_speech` (server: audio) — audio file
- `mcp_create_genai_video` (server: media) — video file
- `mcp_download_youtube_video` (server: search) — video file

**Audio Result Shape:**
```typescript
interface AudioResult extends ToolResult {
  audio_path: string;
  duration: number;     // seconds
}
```

**Video Result Shape:**
```typescript
interface VideoResult extends ToolResult {
  file_path: string;
  duration?: number;    // seconds
  size_mb?: float;
}
```

**Rendering Spec:**
- HTML5 `<audio>` or `<video>` player
- Media files accessed via sandbox file API
- Duration display
- Download button
- For transcriptions (`mcp_audio_transcription`): text panel below player

---

### 9. DataTableRenderer

**Renders:** Database query results, checkpoint lists, server status.

**Tools:**
- `mcp_query_database` (server: web) — SQL query results
- `mcp_list_checkpoints` (server: web) — checkpoint list
- `mcp_server_status` (server: web) — server status
- `mcp_list_presentation_templates` (server: slides) — template list

**Result Shape (database query):**
```typescript
// Result is JSON string containing:
interface QueryResult {
  data: Array<Record<string, unknown>>;
  row_count: number;
}
```

**Rendering Spec:**
- Table with sortable headers
- Pagination for >25 rows
- JSON toggle for raw view
- Copy table as CSV button
- Null values styled distinctly

---

### 10. StatusCard

**Renders:** Simple success/failure status messages for operational tools.

**Tools:**
- `save_file` (server: file)
- `mcp_download_file` (server: download)
- `mcp_start_dev_server`, `mcp_stop_dev_server`, `mcp_restart_dev_server` (server: web)
- `mcp_copy_template`, `mcp_set_env` (server: web)
- `mcp_save_checkpoint`, `mcp_rollback_checkpoint` (server: web)
- `mcp_schedule_task` (server: plan)
- `mcp_create_presentation`, `mcp_add_slide`, `mcp_export_presentation_to_pdf` (server: slides)

**Rendering Spec:**
- Success/error icon with colored background
- Message text
- Metadata row: file path, size, execution time, port, PID (where applicable)
- For dev servers: clickable URL badge, PID badge
- For downloads: file name, size, download button

---

### 11. MarkdownRenderer (Default Text Fallback)

**Renders:** Any tool result that returns primarily text/markdown content.

**Tools:**
- `mcp_reason_about_problem`, `mcp_guard_reasoning` (server: reasoning)
- `mcp_visual_question_answering` (server: vision)
- `mcp_transcribe_youtube_video`, `mcp_analyze_youtube_video`, `mcp_analyze_local_video` (server: vision)
- `mcp_summarize_local_video`, `mcp_compare_multiple_images`, `mcp_compare_multiple_videos` (server: vision)
- `mcp_read_resource_file` (server: reading)

**Rendering Spec:**
- Full markdown rendering (GFM)
- Syntax highlighting in code blocks
- Collapsible sections for long content
- Copy button
- Images rendered inline if referenced

---

### 12. GenericJsonRenderer (Unknown Tools Fallback)

**Renders:** Any tool not matching known categories.

**Rendering Spec:**
- Tool name header with server name badge (if available)
- Collapsible JSON tree viewer for the result
- Syntax-highlighted JSON
- Copy raw JSON button
- Status indicator (success/error)
- "Unknown tool" visual indicator (question mark icon, muted styling)
- Gracefully handles:
  - Tools that no longer exist (historical runs)
  - Custom MCP tools from user-configured servers
  - Composio addon tools

---

## Plan Overview Rendering

The plan timeline is rendered differently from individual tool results. It appears as an expandable section in the panel footer (and also in the chat message list).

**State Source:** `planState` store from `$services/sse.ts`

```typescript
interface PlanState {
  goal: string;
  phases: PhaseInfo[];
  currentPhaseId: string;
}

interface PhaseInfo {
  id: string;
  description: string;
  status: 'pending' | 'in_progress' | 'completed';
  startedAt?: string;
  completedAt?: string;
}
```

**Phase Visual States:**
| Status | Visual |
|--------|--------|
| `completed` | Green checkmark, muted text, optional duration |
| `in_progress` | Highlighted border, pulsing indicator, current phase text |
| `pending` | Dimmed, outlined circle, lighter text |

**Collapsed View:** "Phase {N} of {total} — {current phase description}"
**Expanded View:** Full timeline with all phases and their statuses

---

## Tool Name to Renderer Mapping

This is the definitive mapping from tool names to panel renderers. Use the existing `getServerCategory()` function in `ToolCallMessage.svelte` as the categorization source.

```typescript
const TOOL_RENDERER_MAP: Record<string, string> = {
  // Terminal
  'mcp_run_shell_command': 'terminal',
  'mcp_run_python_code': 'terminal',  // Also shows in code tab

  // File operations
  'edit_file': 'diff',
  'read_file': 'code',
  'save_file': 'status',
  'list_directory': 'file-tree',
  'read_reference_file': 'code',
  'list_reference_directory': 'file-tree',
  'get_reference_projects': 'status',

  // Browser / Screenshots
  'mcp_use_browser': 'browser',
  'mcp_screenshot_url': 'image',
  'mcp_scrape_url': 'markdown',

  // Search
  'mcp_search_google': 'search',
  'mcp_search_google_images': 'image-gallery',
  'mcp_search_wikipedia': 'markdown',
  'mcp_get_wikipedia_article': 'markdown',
  'mcp_get_wikipedia_summary': 'markdown',
  'mcp_get_wikipedia_article_history': 'markdown',

  // Downloads
  'mcp_download_file': 'status',
  'mcp_download_youtube_video': 'status',

  // Audio
  'mcp_audio_transcription': 'markdown',
  'mcp_audio_question_answering': 'markdown',
  'mcp_text_to_speech': 'media-audio',

  // Vision / Video
  'mcp_visual_question_answering': 'markdown',
  'mcp_transcribe_youtube_video': 'markdown',
  'mcp_analyze_youtube_video': 'markdown',
  'mcp_analyze_local_video': 'markdown',
  'mcp_summarize_local_video': 'markdown',
  'mcp_extract_keyframes': 'image-gallery',
  'mcp_compare_multiple_images': 'markdown',
  'mcp_compare_multiple_videos': 'markdown',

  // Web / Dev server
  'mcp_copy_template': 'status',
  'mcp_set_env': 'status',
  'mcp_list_checkpoints': 'data-table',
  'mcp_save_checkpoint': 'status',
  'mcp_rollback_checkpoint': 'status',
  'mcp_query_database': 'data-table',
  'mcp_start_dev_server': 'status',
  'mcp_stop_dev_server': 'status',
  'mcp_restart_dev_server': 'status',
  'mcp_server_status': 'data-table',

  // Media generation
  'mcp_create_genai_image': 'image',
  'mcp_create_genai_image_with_references': 'image',
  'mcp_edit_genai_image': 'image',
  'mcp_create_genai_video': 'media-video',

  // Slides
  'mcp_list_presentation_templates': 'data-table',
  'mcp_load_template_presentation_design': 'markdown',
  'mcp_create_presentation': 'status',
  'mcp_add_slide': 'status',
  'mcp_export_presentation_to_pdf': 'status',
  'mcp_export_presentation_to_pptx': 'status',

  // Mobile (flutter) — mirrors web tools
  'mcp_flutter_copy_template': 'status',
  'mcp_flutter_set_env': 'status',
  'mcp_flutter_list_checkpoints': 'data-table',
  'mcp_flutter_save_checkpoint': 'status',
  'mcp_flutter_rollback_checkpoint': 'status',
  'mcp_flutter_start_dev_server': 'status',
  'mcp_flutter_stop_dev_server': 'status',
  'mcp_flutter_restart_dev_server': 'status',
  'mcp_flutter_server_status': 'data-table',

  // Reasoning
  'mcp_reason_about_problem': 'markdown',
  'mcp_guard_reasoning': 'markdown',

  // Reading
  'mcp_read_resource_file': 'code',

  // Plan tools — intercepted, update planState store
  'mcp_create_plan': 'plan',
  'mcp_update_plan': 'plan',
  'mcp_advance_plan': 'plan',
  'mcp_get_current_plan': 'plan',
  'mcp_update_phase_status': 'plan',
};

// Fallback: 'generic-json' for any tool not in map
```

---

## Existing Frontend Infrastructure

The following is already implemented and should be reused:

1. **`getServerCategory()`** in `ToolCallMessage.svelte` — maps tool names to 16 categories with SVG icons
2. **`planState` store** in `$services/sse.ts` — tracks plan phases, intercepted from SSE
3. **`toolCalls` Map** in `$services/sse.ts` — stores all tool call messages with results
4. **`messages` store** in `$services/sse.ts` — all messages including tool_call type
5. **`PhaseGroup` component** — groups tool calls by phase
6. **`PlanOverview` component** — renders plan timeline
7. **SSE event handling** — already processes `tool_call`, `tool_result`, `mcp_progress` events

---

## Implementation Priority

For US-047 (computer panel shell) and subsequent stories:

1. **Panel Shell** — Container with header, tool slider, content area, plan footer
2. **TerminalRenderer** — Most commonly used, highest value
3. **CodeRenderer + DiffRenderer** — File operations are core
4. **BrowserRenderer** — Screenshots + VNC streaming
5. **SearchResultsRenderer** — Google search is frequent
6. **GenericJsonRenderer** — Catch-all for everything else
7. **ImageGalleryRenderer / MediaPlayer** — Media tools
8. **DataTableRenderer** — Database queries
9. **StatusCard** — Simple operational results
10. **MarkdownRenderer** — Text content fallback
