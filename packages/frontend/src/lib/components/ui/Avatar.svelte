<script lang="ts">
	type Props = {
		src?: string | null;
		alt?: string;
		name?: string;
		size?: 'xs' | 'sm' | 'md' | 'lg';
		class?: string;
	};

	let { src = null, alt = '', name = '', size = 'md', class: className = '' }: Props = $props();

	const sizeClasses: Record<string, string> = {
		xs: 'h-5 w-5 text-[9px]',
		sm: 'h-8 w-8 text-xs',
		md: 'h-10 w-10 text-sm',
		lg: 'h-14 w-14 text-lg'
	};

	function getInitials(name: string): string {
		return name
			.split(' ')
			.map((part) => part[0])
			.filter(Boolean)
			.slice(0, 2)
			.join('')
			.toUpperCase();
	}

	let imgError = $state(false);
	const initials = $derived(getInitials(name || alt));
	const showImage = $derived(src && !imgError);
</script>

<div
	class="relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-foreground text-background font-medium {sizeClasses[
		size
	]} {className}"
>
	{#if showImage}
		<img
			{src}
			alt={alt || name}
			class="h-full w-full object-cover"
			onerror={() => (imgError = true)}
		/>
	{:else}
		<span>{initials}</span>
	{/if}
</div>
