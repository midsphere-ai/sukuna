<script lang="ts">
	type Props = {
		variant?: 'text' | 'circle' | 'rect';
		width?: string;
		height?: string;
		stagger?: number;
		class?: string;
	};

	let { variant = 'text', width, height, stagger, class: className = '' }: Props = $props();

	const variantClasses: Record<string, string> = {
		text: 'h-4 w-full rounded',
		circle: 'h-10 w-10 rounded-full',
		rect: 'h-24 w-full rounded-xl'
	};

	let delay = $derived(stagger != null ? `animation-delay: ${stagger * 0.1}s` : '');
</script>

<div
	class="zen-shimmer {variantClasses[variant]} {className}"
	style:width
	style:height
	style={delay}
	aria-hidden="true"
></div>
