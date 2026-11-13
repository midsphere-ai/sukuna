import { writable, get } from 'svelte/store';
import type { StreamTransport } from '$lib/services/stream-types';
import { flagEnabled } from './featureFlags';

const MAX_EVENTS = 1000;
const EVENT_RATE_WINDOW_MS = 5000;

export interface DebugEvent {
	seq: number;
	type: string;
	payload: Record<string, unknown>;
	at: number;
	transport: StreamTransport;
}

export interface ReconnectEntry {
	at: number;
	reason: string;
	attempt: number;
}

export interface StreamDiagnostics {
	url: string | null;
	transport: StreamTransport;
	connectedAt: number | null;
	disconnectedAt: number | null;
	consecutiveFailures: number;
	reconnectCount: number;
	reconnectHistory: ReconnectEntry[];
	lastSeq: number;
	lastEventAt: number | null;
	eventsReceived: number;
	fallbackActive: boolean;
	fallbackReason: string | null;
}

export const debugBus = writable<DebugEvent[]>([]);

const INITIAL_DIAGNOSTICS: StreamDiagnostics = {
	url: null,
	transport: 'none',
	connectedAt: null,
	disconnectedAt: null,
	consecutiveFailures: 0,
	reconnectCount: 0,
	reconnectHistory: [],
	lastSeq: -1,
	lastEventAt: null,
	eventsReceived: 0,
	fallbackActive: false,
	fallbackReason: null
};

export const streamDiagnostics = writable<StreamDiagnostics>({ ...INITIAL_DIAGNOSTICS });

const debugFlag = flagEnabled('debug-mode');

/** Returns true only when the `debug-mode` feature flag is enabled. */
function isDebugEnabled(): boolean {
	return get(debugFlag);
}

/** Push a single event to the ring buffer. No-op when the debug flag is off. */
export function pushDebugEvent(entry: Omit<DebugEvent, 'at'> & { at?: number }): void {
	if (!isDebugEnabled()) return;
	const at = entry.at ?? Date.now();
	debugBus.update((events) => {
		const next =
			events.length >= MAX_EVENTS ? events.slice(events.length - MAX_EVENTS + 1) : events;
		return [...next, { ...entry, at }];
	});
	streamDiagnostics.update((d) => ({
		...d,
		lastSeq: entry.seq > d.lastSeq ? entry.seq : d.lastSeq,
		lastEventAt: at,
		eventsReceived: d.eventsReceived + 1,
		transport: entry.transport || d.transport
	}));
}

export function clearDebugBus(): void {
	debugBus.set([]);
}

export function resetStreamDiagnostics(): void {
	streamDiagnostics.set({ ...INITIAL_DIAGNOSTICS });
}

export function markConnected(url: string, transport: StreamTransport): void {
	streamDiagnostics.update((d) => ({
		...d,
		url,
		transport,
		connectedAt: Date.now(),
		disconnectedAt: null,
		consecutiveFailures: 0,
		fallbackActive: false,
		fallbackReason: null
	}));
}

export function markReconnectScheduled(attempt: number, reason: string): void {
	streamDiagnostics.update((d) => {
		const entry: ReconnectEntry = { at: Date.now(), reason, attempt };
		const history = [...d.reconnectHistory, entry];
		if (history.length > 50) history.splice(0, history.length - 50);
		return {
			...d,
			consecutiveFailures: attempt,
			reconnectCount: d.reconnectCount + 1,
			reconnectHistory: history
		};
	});
}

export function markFallback(reason: string, transport: StreamTransport): void {
	streamDiagnostics.update((d) => ({
		...d,
		fallbackActive: true,
		fallbackReason: reason,
		transport
	}));
}

export function markDisconnected(): void {
	streamDiagnostics.update((d) => ({ ...d, disconnectedAt: Date.now() }));
}

/**
 * Compute event rate over the last EVENT_RATE_WINDOW_MS. Callers use this from
 * a derived store or by polling; not reactive by itself.
 */
export function computeEventRate(events: DebugEvent[]): number {
	if (events.length === 0) return 0;
	const cutoff = Date.now() - EVENT_RATE_WINDOW_MS;
	let count = 0;
	for (let i = events.length - 1; i >= 0; i--) {
		if (events[i].at < cutoff) break;
		count++;
	}
	return count / (EVENT_RATE_WINDOW_MS / 1000);
}

/**
 * Find the index of the event matching a given sequence. Used by the inline
 * decorator's "find in stream" action.
 */
export function findEventSequence(seq: number): number {
	const events = get(debugBus);
	for (let i = 0; i < events.length; i++) {
		if (events[i].seq === seq) return i;
	}
	return -1;
}
