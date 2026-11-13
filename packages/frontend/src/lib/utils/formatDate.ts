/**
 * Format an ISO date string into a human-readable locale string.
 * Returns '—' for null/undefined/empty values.
 */
export function formatDate(iso: string | null | undefined): string {
	if (!iso) return '—';
	try {
		return new Date(iso).toLocaleString();
	} catch {
		return '—';
	}
}

/**
 * Format an ISO date string into a short date (no time).
 */
export function formatDateShort(iso: string | null | undefined): string {
	if (!iso) return '—';
	try {
		return new Date(iso).toLocaleDateString();
	} catch {
		return '—';
	}
}

/**
 * Format seconds into a human-readable uptime string (e.g. "2d 5h 30m").
 */
export function formatUptime(seconds: number): string {
	if (seconds < 60) return `${seconds}s`;
	const days = Math.floor(seconds / 86400);
	const hours = Math.floor((seconds % 86400) / 3600);
	const minutes = Math.floor((seconds % 3600) / 60);
	const parts: string[] = [];
	if (days > 0) parts.push(`${days}d`);
	if (hours > 0) parts.push(`${hours}h`);
	if (minutes > 0) parts.push(`${minutes}m`);
	return parts.join(' ') || '0m';
}
