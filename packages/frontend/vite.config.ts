import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vitest/config';

const BACKEND_URL = process.env.VITE_BACKEND_URL || 'http://localhost:8000';

const API_ROUTES = ['/api/v1', '/authentication', '/accounts', '/health', '/media'];

export default defineConfig(({ mode }) => ({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		host: process.env.TAURI_DEV_HOST || 'localhost',
		proxy: Object.fromEntries(
			API_ROUTES.map((route) => [
				route,
				{
					target: BACKEND_URL,
					changeOrigin: true,
					bypass(req: { headers: { accept?: string }; url?: string }) {
						// Let SvelteKit handle page navigations (text/html requests)
						if (req.headers.accept?.includes('text/html')) {
							return req.url;
						}
					}
				}
			])
		)
	},
	test: {
		include: ['src/**/*.{test,spec}.{js,ts}'],
		environment: 'jsdom',
		setupFiles: ['src/tests/setup.ts'],
		coverage: {
			provider: 'v8',
			reporter: ['text', 'text-summary', 'html'],
			reportsDirectory: 'coverage',
			include: ['src/lib/**/*.{ts,svelte}'],
			exclude: ['src/lib/**/*.test.ts', 'src/lib/**/*.spec.ts']
		}
	},
	resolve: {
		conditions: mode === 'test' ? ['browser'] : ['browser']
	}
}));
