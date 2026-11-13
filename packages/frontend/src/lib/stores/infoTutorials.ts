import { writable, get } from 'svelte/store';
import { getInfoTutorials, getTutorialContent } from '$api/cms';
import type { Tutorial } from '$api/types';

/** Cached info-button tutorials (fetched once per session) */
export const infoTutorials = writable<Tutorial[]>([]);

/** Content cache keyed by tutorial title */
export const tutorialContentCache = writable<Record<string, string>>({});

let fetched = false;

/** Fetch info-button tutorials (no-op if already fetched) */
export async function loadInfoTutorials(): Promise<void> {
	if (fetched) return;
	fetched = true;
	try {
		const res = await getInfoTutorials();
		infoTutorials.set(res.items);
	} catch {
		// Silently fail — info buttons just won't appear
		infoTutorials.set([]);
	}
}

/** Get a tutorial matching a context keyword from the cached list */
export function getTutorialForContext(context: string): Tutorial | undefined {
	const tutorials = get(infoTutorials);
	const lower = context.toLowerCase();
	return tutorials.find(
		(t) =>
			t.title.toLowerCase().includes(lower) ||
			(t.subtitle && t.subtitle.toLowerCase().includes(lower))
	);
}

/** Fetch full markdown content for a tutorial (cached) */
export async function loadTutorialContent(title: string): Promise<string | null> {
	const cache = get(tutorialContentCache);
	if (cache[title]) return cache[title];
	try {
		const tutorial = await getTutorialContent(title);
		if (tutorial?.markdownText) {
			tutorialContentCache.update((c) => ({ ...c, [title]: tutorial.markdownText! }));
			return tutorial.markdownText;
		}
		return null;
	} catch {
		return null;
	}
}
