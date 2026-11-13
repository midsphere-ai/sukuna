import { writable } from 'svelte/store';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface Toast {
	id: string;
	type: ToastType;
	message: string;
	duration: number;
	exiting?: boolean;
}

const { subscribe, update } = writable<Toast[]>([]);

let counter = 0;

function add(type: ToastType, message: string, duration = 5000): string {
	const id = `toast-${++counter}`;
	const toast: Toast = { id, type, message, duration };

	update((toasts) => [...toasts, toast]);

	if (duration > 0) {
		setTimeout(() => dismiss(id), duration);
	}

	return id;
}

function dismiss(id: string): void {
	update((toasts) => toasts.map((t) => (t.id === id ? { ...t, exiting: true } : t)));
	setTimeout(() => remove(id), 250);
}

function remove(id: string): void {
	update((toasts) => toasts.filter((t) => t.id !== id));
}

export const toasts = {
	subscribe,
	success: (message: string, duration?: number) => add('success', message, duration),
	error: (message: string, duration?: number) => add('error', message, duration),
	warning: (message: string, duration?: number) => add('warning', message, duration),
	info: (message: string, duration?: number) => add('info', message, duration),
	dismiss,
	remove
};
