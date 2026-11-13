import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';
import { Input, Textarea, Select, Checkbox, Toggle, EmptyState } from '$components/ui';

// Helper to create a simple text snippet for Svelte 5
function createSnippet(text: string) {
	return ((anchor: ChildNode) => {
		const node = document.createTextNode(text);
		anchor.before(node);
		return { anchor: node };
	}) as unknown as import('svelte').Snippet;
}

describe('Input', () => {
	it('renders with label', () => {
		render(Input, { props: { label: 'Email', id: 'email' } });
		expect(screen.getByLabelText('Email')).toBeInTheDocument();
	});

	it('renders without label', () => {
		const { container } = render(Input, { props: { placeholder: 'Enter text' } });
		expect(container.querySelector('label')).toBeNull();
		expect(screen.getByPlaceholderText('Enter text')).toBeInTheDocument();
	});

	it('shows required indicator', () => {
		render(Input, { props: { label: 'Name', required: true, id: 'name' } });
		expect(screen.getByText('*')).toBeInTheDocument();
	});

	it('shows error message', () => {
		render(Input, { props: { label: 'Email', error: 'Invalid email', id: 'email' } });
		expect(screen.getByRole('alert')).toHaveTextContent('Invalid email');
		expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true');
	});

	it('supports disabled state', () => {
		render(Input, { props: { label: 'Test', disabled: true, id: 'test' } });
		expect(screen.getByLabelText('Test')).toBeDisabled();
	});

	it('handles input events', async () => {
		const oninput = vi.fn();
		render(Input, { props: { label: 'Test', oninput, id: 'test' } });
		await fireEvent.input(screen.getByLabelText('Test'), { target: { value: 'hello' } });
		expect(oninput).toHaveBeenCalled();
	});

	it('renders password type with show/hide toggle', () => {
		render(Input, { props: { label: 'Password', type: 'password', id: 'pass' } });
		const input = screen.getByLabelText('Password');
		expect(input).toHaveAttribute('type', 'password');
		expect(screen.getByLabelText('Show password')).toBeInTheDocument();
	});

	it('toggles password visibility on click', async () => {
		render(Input, { props: { label: 'Password', type: 'password', id: 'pass' } });
		const input = screen.getByLabelText('Password');
		expect(input).toHaveAttribute('type', 'password');

		await fireEvent.click(screen.getByLabelText('Show password'));
		expect(input).toHaveAttribute('type', 'text');
		expect(screen.getByLabelText('Hide password')).toBeInTheDocument();

		await fireEvent.click(screen.getByLabelText('Hide password'));
		expect(input).toHaveAttribute('type', 'password');
	});

	it('does not show toggle for non-password types', () => {
		render(Input, { props: { label: 'Email', type: 'email', id: 'email' } });
		expect(screen.queryByLabelText('Show password')).not.toBeInTheDocument();
	});

	it('sets aria-describedby when error present', () => {
		render(Input, { props: { label: 'Name', error: 'Required', id: 'name' } });
		const input = screen.getByLabelText('Name');
		expect(input).toHaveAttribute('aria-describedby', 'name-error');
	});

	it('does not set aria-invalid when no error', () => {
		render(Input, { props: { label: 'Name', id: 'name' } });
		const input = screen.getByLabelText('Name');
		expect(input).not.toHaveAttribute('aria-invalid');
	});
});

describe('Textarea', () => {
	it('renders with label', () => {
		render(Textarea, { props: { label: 'Message', id: 'msg' } });
		expect(screen.getByLabelText('Message')).toBeInTheDocument();
		expect(screen.getByLabelText('Message').tagName).toBe('TEXTAREA');
	});

	it('shows error message', () => {
		render(Textarea, { props: { label: 'Note', error: 'Too short', id: 'note' } });
		expect(screen.getByRole('alert')).toHaveTextContent('Too short');
	});

	it('supports custom rows', () => {
		render(Textarea, { props: { label: 'Bio', rows: 5, id: 'bio' } });
		expect(screen.getByLabelText('Bio')).toHaveAttribute('rows', '5');
	});

	it('supports disabled state', () => {
		render(Textarea, { props: { label: 'Test', disabled: true, id: 'test' } });
		expect(screen.getByLabelText('Test')).toBeDisabled();
	});
});

describe('Select', () => {
	it('renders with label and options', () => {
		render(Select, {
			props: { label: 'Country', id: 'country', children: createSnippet('Option A') }
		});
		expect(screen.getByLabelText('Country')).toBeInTheDocument();
		expect(screen.getByLabelText('Country').tagName).toBe('SELECT');
	});

	it('shows error message', () => {
		render(Select, {
			props: {
				label: 'Plan',
				error: 'Required',
				id: 'plan',
				children: createSnippet('Choose')
			}
		});
		expect(screen.getByRole('alert')).toHaveTextContent('Required');
	});

	it('supports disabled state', () => {
		render(Select, {
			props: { label: 'Type', disabled: true, id: 'type', children: createSnippet('Item') }
		});
		expect(screen.getByLabelText('Type')).toBeDisabled();
	});
});

describe('Checkbox', () => {
	it('renders with label', () => {
		render(Checkbox, { props: { label: 'Agree', id: 'agree' } });
		expect(screen.getByLabelText('Agree')).toBeInTheDocument();
		expect(screen.getByRole('checkbox')).toBeInTheDocument();
	});

	it('renders without label', () => {
		render(Checkbox, { props: { id: 'check' } });
		expect(screen.getByRole('checkbox')).toBeInTheDocument();
	});

	it('supports disabled state', () => {
		render(Checkbox, { props: { label: 'Accept', disabled: true, id: 'accept' } });
		expect(screen.getByRole('checkbox')).toBeDisabled();
	});

	it('fires change event', async () => {
		const onchange = vi.fn();
		render(Checkbox, { props: { label: 'Check', onchange, id: 'chk' } });
		await fireEvent.click(screen.getByRole('checkbox'));
		expect(onchange).toHaveBeenCalled();
	});
});

describe('Toggle', () => {
	it('renders with label', () => {
		render(Toggle, { props: { label: 'Notifications', id: 'notif' } });
		expect(screen.getByLabelText('Notifications')).toBeInTheDocument();
		expect(screen.getByRole('switch')).toBeInTheDocument();
	});

	it('renders without label', () => {
		render(Toggle, { props: { id: 'toggle' } });
		expect(screen.getByRole('switch')).toBeInTheDocument();
	});

	it('supports disabled state', () => {
		render(Toggle, { props: { label: 'Dark mode', disabled: true, id: 'dark' } });
		expect(screen.getByRole('switch')).toBeDisabled();
	});

	it('fires change event', async () => {
		const onchange = vi.fn();
		render(Toggle, { props: { label: 'Enable', onchange, id: 'en' } });
		await fireEvent.click(screen.getByRole('switch'));
		expect(onchange).toHaveBeenCalled();
	});
});

describe('EmptyState', () => {
	it('renders title and description', () => {
		render(EmptyState, {
			props: { title: 'No items', description: 'Nothing here yet' }
		});
		expect(screen.getByText('No items')).toBeInTheDocument();
		expect(screen.getByText('Nothing here yet')).toBeInTheDocument();
	});

	it('renders with CTA button', () => {
		render(EmptyState, {
			props: { title: 'Empty', ctaLabel: 'Add item' }
		});
		expect(screen.getByRole('button', { name: 'Add item' })).toBeInTheDocument();
	});

	it('renders CTA as link when href provided', () => {
		render(EmptyState, {
			props: { title: 'Empty', ctaLabel: 'Browse', ctaHref: '/browse' }
		});
		expect(screen.getByRole('link', { name: 'Browse' })).toHaveAttribute('href', '/browse');
	});

	it('renders default illustration when none provided', () => {
		const { container } = render(EmptyState, {
			props: { title: 'Empty' }
		});
		expect(container.querySelector('svg')).toBeInTheDocument();
	});

	it('renders custom illustration snippet', () => {
		render(EmptyState, {
			props: { title: 'Empty', illustration: createSnippet('Custom Icon') }
		});
		expect(screen.getByText('Custom Icon')).toBeInTheDocument();
	});

	it('renders without description', () => {
		const { container } = render(EmptyState, {
			props: { title: 'Empty' }
		});
		expect(screen.getByText('Empty')).toBeInTheDocument();
		expect(container.querySelectorAll('p')).toHaveLength(0);
	});
});
