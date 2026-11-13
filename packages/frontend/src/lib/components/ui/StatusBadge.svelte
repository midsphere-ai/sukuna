<script lang="ts">
	type Props = {
		label: string;
		variant?: 'green' | 'coral' | 'warning' | 'muted' | 'blue' | 'default';
		class?: string;
	};

	let { label, variant = 'default', class: className = '' }: Props = $props();

	const variantClasses: Record<string, string> = {
		default: 'bg-surface text-foreground',
		green: 'bg-success/15 text-success',
		coral: 'bg-accent/10 text-accent',
		warning: 'bg-amber-500/10 text-amber-600',
		muted: 'bg-surface-2 text-subtle',
		blue: 'bg-accent/10 text-accent'
	};
</script>

<span
	class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium {variantClasses[
		variant
	]} {className}"
>
	{label}
</span>
