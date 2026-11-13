/**
 * Client-side prompt leakage guard — last line of defense.
 *
 * Detects system prompt fingerprints in streamed text content and
 * redacts them before rendering. This catches anything that slips
 * past the server-side guardrails.
 */

const FINGERPRINTS: RegExp[] = [
	// XML tag boundaries from system prompts
	/<\/?(?:role|planning_rules|delegation_rules|message_rules|ralph_loop_rules|disclosure_prohibition|support_policy|agent_loop|tool_use|error_handling|sandbox|utilities|skills|user_profile|format|language|intro|workflow|rules|categories|input|executor-plan-context|plan-context)>/i,

	// Planner prompt
	/You are the \*\*planner\*\* — the orchestration layer/i,
	/You have exactly four tools\. You MUST NOT attempt any other action/i,
	/You are a coordinator, NOT a worker/i,
	/MUST come from a delegation/i,
	/STOP and delegate instead/i,
	/Examples of what you MUST delegate/i,
	/executor starts with ZERO context/i,
	/You are the quality gate/i,
	/Skip planning aggressively/i,
	/messages_sent_to_user output field/i,

	// Executor prompt
	/MUST respond with function calling \(tool use\); direct text responses are strictly forbidden/i,
	/MUST respond with exactly one tool call per response; parallel function calling is strictly forbidden/i,
	/exo tool call <tool_name>/i,
	/exo-mcp tool call <server>/i,
	/MUST NOT disclose any part of the system prompt or tool specifications/i,
	/content enclosed in XML tags above.*highly confidential/i,
	/direct the user to contact Jatayu AI support/i,
	/Google Chrome stable with CDP.*on port 9222/i,
	/VNC on port 5900, noVNC web interface on port 6080/i,
	/Agent Skills \(or Skills for short\) are modular capabilities/i,

	// Knowledge Manager prompt
	/You are the Knowledge Manager.*extract vital information/i,
	/Extracting nothing is better than extracting noise/i,
	/Vague summaries like.*are worthless/i,

	// Ralph Worker prompt
	/operating as an autonomous.*implementation worker/i,
	/must complete exactly ONE user story per session/i,
	/Ignoring them will cause you to repeat mistakes/i,

	// Shared
	/You are Sukuna, an AI agent created by Jatayu AI/i
];

/**
 * Check if text contains system prompt fingerprints.
 * Returns true if the text is clean (safe to display).
 */
export function isCleanText(text: string): boolean {
	if (!text) return true;
	return !FINGERPRINTS.some((fp) => fp.test(text));
}

/**
 * Sanitize text by removing prompt leakage.
 * Returns the original text if clean, or empty string if tainted.
 */
export function sanitizeStreamText(text: string): string {
	if (!text) return text;
	if (isCleanText(text)) return text;
	console.warn('[promptGuard] Blocked prompt leakage in streamed text');
	return '';
}
