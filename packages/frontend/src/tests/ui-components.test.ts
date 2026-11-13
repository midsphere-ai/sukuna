import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { Button, Card, Badge, Avatar, Skeleton } from '$components/ui';

describe('Button', () => {
	it('renders as a button by default', () => {
		render(Button, { props: { children: createSnippet('Click me') } });
		expect(screen.getByRole('button')).toBeInTheDocument();
		expect(screen.getByText('Click me')).toBeInTheDocument();
	});

	it('renders as an anchor when href is provided', () => {
		render(Button, { props: { href: '/test', children: createSnippet('Link') } });
		expect(screen.getByRole('link')).toHaveAttribute('href', '/test');
	});

	it('applies primary variant classes', () => {
		render(Button, { props: { variant: 'primary', children: createSnippet('Primary') } });
		const btn = screen.getByRole('button');
		expect(btn.className).toContain('bg-foreground');
		expect(btn.className).toContain('text-background');
	});

	it('applies bordered variant classes', () => {
		render(Button, { props: { variant: 'bordered', children: createSnippet('Bordered') } });
		const btn = screen.getByRole('button');
		expect(btn.className).toContain('border');
	});

	it('supports disabled state', () => {
		render(Button, { props: { disabled: true, children: createSnippet('Disabled') } });
		expect(screen.getByRole('button')).toBeDisabled();
	});
});

describe('Card', () => {
	it('renders as a div by default', () => {
		const { container } = render(Card, { props: { children: createSnippet('Content') } });
		const card = container.firstElementChild!;
		expect(card.tagName).toBe('DIV');
		expect(card.className).toContain('rounded-xl');
	});

	it('renders as article when specified', () => {
		const { container } = render(Card, {
			props: { as: 'article', children: createSnippet('Article') }
		});
		expect(container.firstElementChild!.tagName).toBe('ARTICLE');
	});
});

describe('Badge', () => {
	it('renders with default variant', () => {
		render(Badge, { props: { children: createSnippet('Status') } });
		const badge = screen.getByText('Status');
		expect(badge.className).toContain('rounded-full');
	});

	it('applies coral variant', () => {
		render(Badge, { props: { variant: 'coral', children: createSnippet('Active') } });
		const badge = screen.getByText('Active');
		expect(badge.className).toContain('text-accent');
	});
});

describe('Avatar', () => {
	it('shows initials when no image provided', () => {
		render(Avatar, { props: { name: 'John Doe' } });
		expect(screen.getByText('JD')).toBeInTheDocument();
	});

	it('shows single initial for single name', () => {
		render(Avatar, { props: { name: 'Alice' } });
		expect(screen.getByText('A')).toBeInTheDocument();
	});

	it('renders image when src provided', () => {
		render(Avatar, { props: { src: '/avatar.png', alt: 'User' } });
		const img = screen.getByRole('img');
		expect(img).toHaveAttribute('src', '/avatar.png');
	});
});

describe('Skeleton', () => {
	it('renders with text variant by default', () => {
		const { container } = render(Skeleton);
		const el = container.firstElementChild!;
		expect(el.className).toContain('zen-shimmer');
		expect(el.className).toContain('rounded');
		expect(el.getAttribute('aria-hidden')).toBe('true');
	});

	it('renders circle variant', () => {
		const { container } = render(Skeleton, { props: { variant: 'circle' } });
		expect(container.firstElementChild!.className).toContain('rounded-full');
	});

	it('renders rect variant', () => {
		const { container } = render(Skeleton, { props: { variant: 'rect' } });
		expect(container.firstElementChild!.className).toContain('rounded-xl');
	});
});

// Helper to create a simple text snippet for Svelte 5
function createSnippet(text: string) {
	return ((anchor: ChildNode) => {
		const node = document.createTextNode(text);
		anchor.before(node);
		return { anchor: node };
	}) as unknown as import('svelte').Snippet;
}
