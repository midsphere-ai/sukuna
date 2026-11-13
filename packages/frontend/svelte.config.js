import adapterNode from '@sveltejs/adapter-node';
import adapterStatic from '@sveltejs/adapter-static';

const isTauri = process.env.VITE_TAURI === 'true';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		adapter: isTauri ? adapterStatic({ fallback: 'index.html' }) : adapterNode(),
		alias: {
			$components: 'src/lib/components',
			'$components/*': 'src/lib/components/*',
			$stores: 'src/lib/stores',
			'$stores/*': 'src/lib/stores/*',
			$services: 'src/lib/services',
			'$services/*': 'src/lib/services/*',
			$api: 'src/lib/api',
			'$api/*': 'src/lib/api/*',
			$utils: 'src/lib/utils',
			'$utils/*': 'src/lib/utils/*',
			$types: 'src/lib/types',
			'$types/*': 'src/lib/types/*',
			$assets: 'src/lib/assets',
			'$assets/*': 'src/lib/assets/*'
		}
	}
};

export default config;
