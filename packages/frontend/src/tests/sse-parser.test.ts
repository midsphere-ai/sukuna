import { describe, it, expect } from 'vitest';
import { createSSEParserState, parseSSELines } from '$lib/utils/sseParser';

interface SSEEvent {
	type?: string;
	[key: string]: unknown;
}

interface CollectedEvent {
	type: string;
	data: SSEEvent;
}

function collect(): { events: CollectedEvent[]; handler: (type: string, data: SSEEvent) => void } {
	const events: CollectedEvent[] = [];
	return { events, handler: (type: string, data: SSEEvent) => events.push({ type, data }) };
}

describe('SSE parser', () => {
	it('createSSEParserState returns initial state', () => {
		const state = createSSEParserState();
		expect(state.eventType).toBe('');
		expect(state.dataLines).toEqual([]);
	});

	it('parses a simple event', () => {
		const { events, handler } = collect();
		const buffer = 'data: {"type":"text","content":"hello"}\n\n';
		const remaining = parseSSELines(buffer, handler);
		expect(events).toHaveLength(1);
		expect(events[0].type).toBe('text');
		expect(events[0].data.content).toBe('hello');
		expect(remaining).toBe('');
	});

	it('parses named events', () => {
		const { events, handler } = collect();
		const buffer = 'event: status\ndata: {"state":"running"}\n\n';
		parseSSELines(buffer, handler);
		expect(events).toHaveLength(1);
		expect(events[0].type).toBe('status');
		expect(events[0].data.state).toBe('running');
	});

	it('ignores SSE comments (keepalives)', () => {
		const { events, handler } = collect();
		const buffer = ': keepalive\ndata: {"type":"text"}\n\n';
		parseSSELines(buffer, handler);
		expect(events).toHaveLength(1);
	});

	it('handles multi-line data', () => {
		const { events, handler } = collect();
		const obj = { type: 'text', content: 'hello\nworld' };
		const json = JSON.stringify(obj);
		const buffer = `data: ${json}\n\n`;
		parseSSELines(buffer, handler);
		expect(events).toHaveLength(1);
		expect(events[0].data.content).toBe('hello\nworld');
	});

	it('handles multiple data: lines joined with newline', () => {
		const { events, handler } = collect();
		// Per SSE spec, multiple data: lines are joined with \n
		const buffer = 'data: {"type":\ndata: "text"}\n\n';
		parseSSELines(buffer, handler);
		expect(events).toHaveLength(1);
		expect(events[0].data.type).toBe('text');
	});

	it('returns remaining incomplete line', () => {
		const { events, handler } = collect();
		const buffer = 'data: {"type":"text"}\n\ndata: {"type":"inc';
		const remaining = parseSSELines(buffer, handler);
		expect(events).toHaveLength(1);
		expect(remaining).toBe('data: {"type":"inc');
	});

	it('handles \\r\\n line endings', () => {
		const { events, handler } = collect();
		const buffer = 'data: {"type":"text"}\r\n\r\n';
		parseSSELines(buffer, handler);
		expect(events).toHaveLength(1);
	});

	it('ignores malformed JSON', () => {
		const { events, handler } = collect();
		const buffer = 'data: not-json\n\ndata: {"type":"valid"}\n\n';
		parseSSELines(buffer, handler);
		expect(events).toHaveLength(1);
		expect(events[0].data.type).toBe('valid');
	});

	it('handles data: with no space after colon', () => {
		const { events, handler } = collect();
		const buffer = 'data:{"type":"text"}\n\n';
		parseSSELines(buffer, handler);
		expect(events).toHaveLength(1);
		expect(events[0].data.type).toBe('text');
	});

	it('uses type from data when no event header', () => {
		const { events, handler } = collect();
		const buffer = 'data: {"type":"custom_event","value":42}\n\n';
		parseSSELines(buffer, handler);
		expect(events[0].type).toBe('custom_event');
	});

	it('event header overrides data type', () => {
		const { events, handler } = collect();
		const buffer = 'event: override\ndata: {"type":"from_data"}\n\n';
		parseSSELines(buffer, handler);
		expect(events[0].type).toBe('override');
	});

	it('handles multiple events in one buffer', () => {
		const { events, handler } = collect();
		const buffer = 'data: {"type":"a"}\n\ndata: {"type":"b"}\n\ndata: {"type":"c"}\n\n';
		parseSSELines(buffer, handler);
		expect(events).toHaveLength(3);
		expect(events.map((e) => e.data.type)).toEqual(['a', 'b', 'c']);
	});

	it('preserves state across chunked reads', () => {
		const { events, handler } = collect();
		const state = createSSEParserState();

		// First chunk has event header and start of data
		const remaining = parseSSELines('event: status\ndata: {"sta', handler, state);
		expect(events).toHaveLength(0);

		// Second chunk completes the event
		parseSSELines(remaining + 'te":"ok"}\n\n', handler, state);
		expect(events).toHaveLength(1);
		expect(events[0].type).toBe('status');
		expect(events[0].data.state).toBe('ok');
	});

	it('resets event type after dispatch', () => {
		const { events, handler } = collect();
		const state = createSSEParserState();

		parseSSELines('event: first\ndata: {"a":1}\n\ndata: {"type":"second"}\n\n', handler, state);
		expect(events[0].type).toBe('first');
		expect(events[1].type).toBe('second');
	});

	it('blank line with no data resets event type', () => {
		const { events, handler } = collect();
		const state = createSSEParserState();

		// event header followed by blank (no data) then new event
		parseSSELines('event: stale\n\ndata: {"type":"fresh"}\n\n', handler, state);
		expect(events).toHaveLength(1);
		expect(events[0].type).toBe('fresh');
	});
});
