<script lang="ts">
	import type { ToolIcon } from '$lib/utils/toolLabels';
	type Props = {
		icon: ToolIcon;
		size?: number;
	};
	let { icon, size = 14 }: Props = $props();
	let s = $derived(`${size}`);
</script>

{#if icon === 'folder'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path
			d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"
		/></svg
	>
{:else if icon === 'file'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path
			d="M14 2v4a2 2 0 0 0 2 2h4"
		/></svg
	>
{:else if icon === 'file-plus'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path
			d="M14 2v4a2 2 0 0 0 2 2h4"
		/><path d="M12 18v-6" /><path d="M9 15h6" /></svg
	>
{:else if icon === 'file-edit'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="M12 22h6a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v10" /><path
			d="M14 2v4a2 2 0 0 0 2 2h4"
		/><path d="M10.4 12.6a2 2 0 0 0-3 3L12 21h3v-3Z" /></svg
	>
{:else if icon === 'file-x'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /><path
			d="M14 2v4a2 2 0 0 0 2 2h4"
		/><path d="m14.5 12.5-5 5" /><path d="m9.5 12.5 5 5" /></svg
	>
{:else if icon === 'file-arrow'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="M4 22h14a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v4" /><path
			d="M14 2v4a2 2 0 0 0 2 2h4"
		/><path d="M2 15h10" /><path d="m9 18 3-3-3-3" /></svg
	>
{:else if icon === 'file-search'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="M14 2v4a2 2 0 0 0 2 2h4" /><path
			d="M4.268 21a2 2 0 0 0 1.727 1H18a2 2 0 0 0 2-2V7l-5-5H6a2 2 0 0 0-2 2v3"
		/><circle cx="6" cy="14" r="3" /><path d="m9 17-1.5-1.5" /></svg
	>
{:else if icon === 'terminal'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><polyline points="4 17 10 11 4 5" /><line x1="12" x2="20" y1="19" y2="19" /></svg
	>
{:else if icon === 'code'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" /></svg
	>
{:else if icon === 'search'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg
	>
{:else if icon === 'globe'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><circle cx="12" cy="12" r="10" /><path d="M2 12h20" /><path
			d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"
		/></svg
	>
{:else if icon === 'link'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" /><path
			d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"
		/></svg
	>
{:else if icon === 'camera'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path
			d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3Z"
		/><circle cx="12" cy="13" r="3" /></svg
	>
{:else if icon === 'download'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline
			points="7 10 12 15 17 10"
		/><line x1="12" x2="12" y1="15" y2="3" /></svg
	>
{:else if icon === 'book'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" /></svg
	>
{:else if icon === 'mic'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" /><path
			d="M19 10v2a7 7 0 0 1-14 0v-2"
		/><line x1="12" x2="12" y1="19" y2="22" /></svg
	>
{:else if icon === 'eye'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></svg
	>
{:else if icon === 'video'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5" /><rect
			x="2"
			y="6"
			width="14"
			height="12"
			rx="2"
		/></svg
	>
{:else if icon === 'sparkles'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path
			d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"
		/></svg
	>
{:else if icon === 'database'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14a9 3 0 0 0 18 0V5" /><path
			d="M3 12a9 3 0 0 0 18 0"
		/></svg
	>
{:else if icon === 'server'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><rect width="20" height="8" x="2" y="2" rx="2" ry="2" /><rect
			width="20"
			height="8"
			x="2"
			y="14"
			rx="2"
			ry="2"
		/><line x1="6" x2="6.01" y1="6" y2="6" /><line x1="6" x2="6.01" y1="18" y2="18" /></svg
	>
{:else if icon === 'package'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="m7.5 4.27 9 5.15" /><path
			d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"
		/><path d="m3.3 7 8.7 5 8.7-5" /><path d="M12 22V12" /></svg
	>
{:else if icon === 'git-save'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path
			d="M15.22 20.7a1 1 0 0 1-1.09-.22L12 18.34l-2.12 2.12a1 1 0 0 1-1.72-.7V12a1 1 0 0 1 1-1h5.69a1 1 0 0 1 1 1v8a1 1 0 0 1-.63.93Z"
		/><circle cx="12" cy="5" r="3" /></svg
	>
{:else if icon === 'settings'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><line x1="4" x2="4" y1="21" y2="14" /><line x1="4" x2="4" y1="10" y2="3" /><line
			x1="12"
			x2="12"
			y1="21"
			y2="12"
		/><line x1="12" x2="12" y1="8" y2="3" /><line x1="20" x2="20" y1="21" y2="16" /><line
			x1="20"
			x2="20"
			y1="12"
			y2="3"
		/><line x1="2" x2="6" y1="14" y2="14" /><line x1="10" x2="14" y1="8" y2="8" /><line
			x1="18"
			x2="22"
			y1="16"
			y2="16"
		/></svg
	>
{:else if icon === 'layout'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><rect width="18" height="18" x="3" y="3" rx="2" /><path d="M3 9h18" /><path d="M9 21V9" /></svg
	>
{:else if icon === 'slides'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><rect width="18" height="12" x="3" y="4" rx="2" /><path d="M8 20h8" /><path
			d="M12 16v4"
		/></svg
	>
{:else if icon === 'clipboard'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" /><path
			d="M15 2H9a1 1 0 0 0-1 1v2a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1Z"
		/></svg
	>
{:else if icon === 'message'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"><path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" /></svg
	>
{:else if icon === 'brain'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path
			d="M12 2a8 8 0 0 0-8 8c0 3.4 2.1 6.3 5 7.5V20h6v-2.5c2.9-1.2 5-4.1 5-7.5a8 8 0 0 0-8-8Z"
		/><path d="M10 22h4" /></svg
	>
{:else if icon === 'shield'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path
			d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"
		/></svg
	>
{:else if icon === 'paperclip'}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path
			d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"
		/></svg
	>
{:else}
	<svg
		xmlns="http://www.w3.org/2000/svg"
		width={s}
		height={s}
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
		><path
			d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76Z"
		/></svg
	>
{/if}
