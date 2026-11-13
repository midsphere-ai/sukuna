/**
 * Consistent color assignment per user_id for multi-participant conversations.
 * Uses a small palette of muted, accessible colors that work on both light and dark backgrounds.
 */

const USER_COLORS = [
	'#6366f1', // indigo
	'#ec4899', // pink
	'#f59e0b', // amber
	'#10b981', // emerald
	'#8b5cf6', // violet
	'#ef4444', // red
	'#06b6d4', // cyan
	'#f97316', // orange
	'#14b8a6', // teal
	'#a855f7' // purple
];

const colorCache = new Map<string, string>();

export function getUserColor(userId: string): string {
	const cached = colorCache.get(userId);
	if (cached) return cached;

	// Simple hash to get a consistent index
	let hash = 0;
	for (let i = 0; i < userId.length; i++) {
		hash = ((hash << 5) - hash + userId.charCodeAt(i)) | 0;
	}
	const color = USER_COLORS[Math.abs(hash) % USER_COLORS.length];
	colorCache.set(userId, color);
	return color;
}
