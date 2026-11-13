import { render, screen } from '@testing-library/svelte';
import { describe, it, expect } from 'vitest';
import PublicNav from '$components/layout/PublicNav.svelte';
import Footer from '$components/layout/Footer.svelte';

describe('PublicNav component', () => {
	it('renders Jatayu AI logo link', () => {
		render(PublicNav);
		const logos = screen.getAllByAltText('Jatayu AI');
		expect(logos.length).toBeGreaterThan(0);
		expect(logos[0].closest('a')).toHaveAttribute('href', '/');
	});

	it('renders Sign In link', () => {
		render(PublicNav);
		const signIn = screen.getByText('Sign In');
		expect(signIn).toBeInTheDocument();
		expect(signIn.closest('a')).toHaveAttribute('href', '/login');
	});

	it('renders Sign Up link', () => {
		render(PublicNav);
		const signUp = screen.getByText('Sign Up');
		expect(signUp).toBeInTheDocument();
		expect(signUp.closest('a')).toHaveAttribute('href', '/signup');
	});

	it('has navigation landmark', () => {
		render(PublicNav);
		expect(screen.getByRole('navigation')).toBeInTheDocument();
	});

	it('Sign Up button uses primary variant styling', () => {
		render(PublicNav);
		const signUp = screen.getByText('Sign Up');
		const link = signUp.closest('a');
		expect(link?.className).toContain('bg-foreground');
		expect(link?.className).toContain('text-background');
	});
});

describe('Footer component', () => {
	it('renders Jatayu AI logo link', () => {
		render(Footer);
		const logos = screen.getAllByAltText('Jatayu AI');
		expect(logos.length).toBeGreaterThan(0);
		expect(logos[0].closest('a')).toHaveAttribute('href', '/');
	});

	it('renders tagline', () => {
		render(Footer);
		expect(screen.getByText('Think fast, Build even faster.')).toBeInTheDocument();
	});

	it('renders Tutorials link', () => {
		render(Footer);
		const link = screen.getByText('Tutorials');
		expect(link).toBeInTheDocument();
		expect(link.closest('a')).toHaveAttribute('href', '/tutorials');
	});

	it('renders Changelog link', () => {
		render(Footer);
		const link = screen.getByText('Changelog');
		expect(link.closest('a')).toHaveAttribute('href', '/changelog');
	});

	it('renders Support link', () => {
		render(Footer);
		const link = screen.getByText('Support');
		expect(link.closest('a')).toHaveAttribute('href', '/support');
	});

	it('renders Terms link', () => {
		render(Footer);
		const link = screen.getByText('Terms');
		expect(link.closest('a')).toHaveAttribute('href', '/terms');
	});

	it('renders Privacy link', () => {
		render(Footer);
		const link = screen.getByText('Privacy');
		expect(link.closest('a')).toHaveAttribute('href', '/privacy');
	});

	it('renders copyright with current year', () => {
		render(Footer);
		const year = new Date().getFullYear().toString();
		expect(screen.getByText(new RegExp(`${year} Jatayu AI`))).toBeInTheDocument();
	});

	it('has footer landmark', () => {
		render(Footer);
		expect(screen.getByRole('contentinfo')).toBeInTheDocument();
	});

	it('renders five navigation links', () => {
		render(Footer);
		const links = screen.getAllByRole('link').filter((l) => l.getAttribute('href') !== '/');
		expect(links).toHaveLength(5);
	});
});
