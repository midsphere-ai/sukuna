# Midsphere Frontend

SvelteKit frontend for the Midsphere AI agent orchestration platform.

## Tech Stack

- **SvelteKit** with Svelte 5 (runes mode)
- **TypeScript** for type safety
- **Tailwind CSS 4** for styling
- **Vite** for bundling

## Development

```bash
npm install
npm run dev          # Start dev server (http://localhost:5173)
npm run check        # TypeScript check
npm run lint         # ESLint
npm run test:unit    # Unit tests
npm run build        # Production build
```

## Project Structure

```
src/
├── lib/
│   ├── api/             # API client and typed endpoints
│   │   ├── client.ts    # Central fetch wrapper (auth injection, error handling)
│   │   ├── chat.ts      # Chat/task API (start, cancel, status, events, HITL)
│   │   ├── auth.ts      # Login, register, Google auth
│   │   ├── conversations.ts  # Conversation CRUD, sharing
│   │   └── types.ts     # Shared TypeScript types
│   ├── stores/          # Svelte stores (global state)
│   │   ├── auth.ts      # Auth token + user (localStorage/sessionStorage)
│   │   ├── chatInput.ts # Chat input state
│   │   └── toast.ts     # Toast notifications
│   ├── services/        # Business logic services
│   │   ├── sse.ts       # SSE streaming (status polling, reconnection, HITL)
│   │   └── chatExport.ts
│   ├── components/      # Reusable components
│   │   └── chat/        # Chat UI (messages, input, phases, plan overview)
│   └── utils/           # Utilities
│       └── sseParser.ts # Multi-line SSE parser (spec-compliant)
├── routes/
│   ├── (app)/           # Authenticated app routes
│   │   ├── +layout.svelte   # Main app layout (sidebar, auth guard)
│   │   └── chat/[id]/       # Chat page
│   ├── (public)/        # Public routes
│   │   ├── login/       # Login page
│   │   └── shared/[id]/ # Shared conversation viewer
│   └── +layout.svelte   # Root layout
```

## Key Architecture

### Auth Flow

Auth tokens are stored based on the "Remember me" preference:

- **Remember me checked** → `localStorage` (persists across browser restarts)
- **Remember me unchecked** → `sessionStorage` (cleared on tab close)

The `persistSession` store in `auth.ts` tracks which storage to use. On login, `setAuth(token, user, rememberMe)` writes to the correct storage and clears the other.

### SSE Streaming

The SSE service (`services/sse.ts`) handles the async task model:

1. **Status polling** — For `queued`/`provisioning` tasks, `waitForRunning()` polls `GET /status` every 2s
2. **SSE connection** — Once `running`, connects to the SSE stream endpoint
3. **Event processing** — Parses messages, tool calls, tool results, steps, status changes
4. **Inactivity timeout** — 90s timeout triggers reconnection
5. **HITL support** — Surfaces "ask" prompts to the user, submits responses

Use `connectToRunWithPolling(conversationId, initialStatus, runId)` — it automatically handles the polling→streaming transition.

### SSE Parser

The parser in `utils/sseParser.ts` follows the SSE specification:

- Multiple `data:` lines are collected in an array and joined with `\n` on dispatch
- Bare `data:` (no content) pushes an empty string
- Events are dispatched on blank lines

### API Client

`api/client.ts` provides a central `api` object with `get`, `post`, `patch`, `put`, `delete`, `upload` methods:

- Auto-injects `Authorization: Bearer <token>` header
- Detects `FormData` body and skips JSON serialization
- On 401/403: clears auth and redirects to `/login`
- Shows toast notifications for errors (unless `skipErrorHandling: true`)

## Environment Variables

| Variable            | Description          | Default            |
| ------------------- | -------------------- | ------------------ |
| `VITE_API_BASE_URL` | Backend API base URL | `""` (same origin) |
