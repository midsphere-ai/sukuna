export interface SSEParserState {
	eventType: string;
	dataLines: string[];
	eventId: string;
}

export function createSSEParserState(): SSEParserState {
	return { eventType: '', dataLines: [], eventId: '' };
}

/**
 * Parse SSE lines from a text buffer. Returns the remaining incomplete line.
 * Handles named events (event: ...) and data lines, separated by blank lines.
 * Ignores SSE comments (lines starting with ':') such as keepalives.
 * Supports multi-line data per SSE spec (multiple data: lines joined with \n).
 *
 * Pass a stable parser state across chunks to preserve partial events.
 */
export function parseSSELines<T extends { type?: string }>(
	buffer: string,
	handler: (eventType: string, data: T, eventId?: string) => void,
	state: SSEParserState = createSSEParserState()
): string {
	const lines = buffer.split('\n');
	const remaining = lines.pop() ?? '';

	for (const rawLine of lines) {
		const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;

		if (line.startsWith(':')) {
			continue;
		}

		if (line.startsWith('event:')) {
			state.eventType = line.slice(6).trim();
			continue;
		}

		if (line.startsWith('id:')) {
			state.eventId = line.startsWith('id: ') ? line.slice(4) : line.slice(3);
			continue;
		}

		if (line.startsWith('data:')) {
			const content = line.startsWith('data: ') ? line.slice(6) : line.slice(5);
			state.dataLines.push(content);
			continue;
		}

		if (line.trim() === '') {
			if (state.dataLines.length === 0) {
				state.eventType = '';
				state.eventId = '';
				continue;
			}

			const fullData = state.dataLines.join('\n');
			try {
				const data = JSON.parse(fullData) as T;
				const eventType = state.eventType || (typeof data.type === 'string' ? data.type : '');
				try {
					handler(eventType, data, state.eventId || undefined);
				} catch (handlerErr) {
					console.error('[SSE] Error in event handler for', eventType, ':', handlerErr);
				}
			} catch (err) {
				console.warn(
					'[SSE] Dropped malformed JSON event:',
					(err as Error).message,
					fullData.slice(0, 200)
				);
			}

			state.eventType = '';
			state.dataLines = [];
			state.eventId = '';
		}
	}

	return remaining;
}
