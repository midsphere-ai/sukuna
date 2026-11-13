import { describe, it, expect } from 'vitest';
import type { Message } from '$services/sse';
import { exportToJson, exportToMarkdown } from '$lib/services/chatExport';

describe('chatExport', () => {
	it('exports markdown tool activity without exposing raw tool internals', () => {
		const messages: Message[] = [
			{
				type: 'tool_call',
				callId: 'tc-1',
				toolName: 'mcp_search_google',
				args: { _exo_tool_brief: 'Researching market size for Q4' },
				status: 'error',
				error: 'timeout while calling provider'
			}
		];

		const markdown = exportToMarkdown('Test Chat', messages);

		expect(markdown).toContain('> Researching market size for Q4');
		expect(markdown).not.toContain('mcp_search_google');
		expect(markdown).not.toContain('**Tool:**');
		expect(markdown).not.toContain('timeout while calling provider');
		expect(markdown).not.toContain('**Error:**');
	});

	it('exports message tool call as visible UI text body in markdown', () => {
		const messages: Message[] = [
			{
				type: 'tool_call',
				callId: 'tc-2',
				toolName: 'message',
				args: { type: 'info' },
				status: 'success',
				result: { message: 'Findings saved successfully. Proceeding to synthesis.' }
			}
		];

		const markdown = exportToMarkdown('Test Chat', messages);

		expect(markdown).toContain('> Findings saved successfully. Proceeding to synthesis.');
		expect(markdown).not.toContain('**Tool:**');
	});

	it('exports json activities with ui-safe fields only', () => {
		const messages: Message[] = [
			{
				type: 'tool_call',
				callId: 'tc-1',
				toolName: 'mcp_run_shell_command',
				args: { _exo_tool_brief: 'Checking repository state', command: 'git status --short' },
				status: 'running'
			},
			{
				type: 'tool_call',
				callId: 'tc-2',
				toolName: 'mcp_search_google',
				args: { _exo_tool_brief: 'Collecting reference links', query: 'micro saas examples' },
				status: 'error',
				error: 'upstream unavailable'
			}
		];

		const exported = JSON.parse(exportToJson('Test Chat', messages)) as {
			messages: Array<Record<string, unknown>>;
		};
		const [runningActivity, completedActivity] = exported.messages;

		expect(runningActivity).toMatchObject({
			type: 'activity',
			text: 'Checking repository state',
			status: 'running'
		});
		expect(completedActivity).toMatchObject({
			type: 'activity',
			text: 'Collecting reference links',
			status: 'completed'
		});

		for (const activity of [runningActivity, completedActivity]) {
			expect(activity).not.toHaveProperty('toolName');
			expect(activity).not.toHaveProperty('args');
			expect(activity).not.toHaveProperty('error');
			expect(activity).not.toHaveProperty('result');
		}
	});
});
