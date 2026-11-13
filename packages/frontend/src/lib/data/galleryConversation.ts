import {
	messages,
	toolCalls,
	planState,
	runStatus,
	tokenUsage,
	activeStep,
	type Message,
	type ToolCallMessage as ToolCallMsg,
	type PlanState
} from '$services/sse';

/**
 * Gallery / demo conversation — showcases a long, realistic agent session
 * with tool calls, phases, HITL, reasoning, and result messages.
 *
 * Navigate to /chat/gallery to view.
 */

export const GALLERY_ID = 'gallery';
export const GALLERY_TITLE = 'Build a Q4 sales dashboard';

export function isGalleryConversation(id: string): boolean {
	return id === GALLERY_ID;
}

export function loadGalleryConversation(): void {
	const mockMessages: Message[] = [
		// ──────────────────── Turn 1 ────────────────────
		{
			type: 'user',
			text: 'Create a data dashboard that visualizes our Q4 sales performance. I have sales_q4.csv with monthly revenue, customer acquisition costs, and product category breakdowns. Make it look polished and modern.',
			files: ['sales_q4.csv']
		},

		// Reasoning
		{
			type: 'reasoning',
			text: "The user wants a comprehensive Q4 sales dashboard. I'll need to: 1) Analyze the CSV to understand data shape — columns, row count, date range, categories. 2) Design a dashboard layout with KPI cards, trend charts, and breakdowns. 3) Build it with HTML/CSS/JS using Chart.js for visualizations. 4) Preview in the browser and iterate. Let me start with data analysis."
		},

		// Step 1
		{ type: 'step', stepNumber: 1, status: 'started', maxSteps: 8 },

		// Plan is set via planState store (not as a message)

		{
			type: 'assistant',
			text: "I'll build a comprehensive Q4 sales dashboard for you. Let me start by analyzing your CSV data to understand the structure, then design and build the visualization.",
			isStreaming: false
		},

		// ── Phase 1: Analyze ──

		{
			type: 'tool_call',
			callId: 'tc-001',
			toolName: 'shell',
			args: {
				action: 'python',
				message: 'Loading the sales data to understand its structure and content.',
				code_block:
					"import pandas as pd\n\ndf = pd.read_csv('/workspace/sales_q4.csv')\nprint(f'Shape: {df.shape}')\nprint(f'Columns: {list(df.columns)}')\nprint(df.head(5).to_string())\nprint(f'\\nRevenue by month:')\nprint(df.groupby('month')['revenue'].sum().to_string())"
			},
			status: 'success',
			result: {
				output:
					"Shape: (450, 8)\nColumns: ['date', 'month', 'product_category', 'revenue', 'units_sold', 'cac', 'region', 'channel']\n\n         date month product_category  revenue  units_sold    cac region channel\n0  2024-10-01   Oct      Electronics    12450          89  34.50  North  Online\n1  2024-10-01   Oct          Apparel     8920         156  22.10  South  Retail\n2  2024-10-01   Oct    Home & Garden     6780          67  41.20   East  Online\n3  2024-10-02   Oct      Electronics    15670         112  31.80   West  Online\n4  2024-10-02   Oct          Apparel     7340         134  25.60  North  Retail\n\nRevenue by month:\nmonth\nDec    892450\nNov    845230\nOct    756890\nName: revenue, dtype: int64"
			},
			durationMs: 2340,
			phaseId: 'phase_1'
		},

		{
			type: 'tool_call',
			callId: 'tc-002',
			toolName: 'shell',
			args: {
				action: 'python',
				message: 'Breaking down revenue by category, region, and channel to find the key insights.',
				code_block:
					"import pandas as pd\n\ndf = pd.read_csv('/workspace/sales_q4.csv')\n\n# Deeper analysis\nprint('Category breakdown:')\nprint(df.groupby('product_category')['revenue'].sum().sort_values(ascending=False).to_string())\nprint(f'\\nRegional breakdown:')\nprint(df.groupby('region')['revenue'].sum().sort_values(ascending=False).to_string())\nprint(f'\\nChannel split:')\nprint(df.groupby('channel')['revenue'].sum().to_string())\nprint(f'\\nAvg CAC by month:')\nprint(df.groupby('month')['cac'].mean().round(2).to_string())\nprint(f'\\nTotal revenue: ${df[\"revenue\"].sum():,.0f}')\nprint(f'Total units: {df[\"units_sold\"].sum():,}')"
			},
			status: 'success',
			result: {
				output:
					'Category breakdown:\nproduct_category\nElectronics      1045670\nApparel           678340\nHome & Garden     412890\nSports            357670\nName: revenue, dtype: int64\n\nRegional breakdown:\nregion\nNorth    698450\nWest     594550\nEast     589230\nSouth    612340\nName: revenue, dtype: int64\n\nChannel split:\nchannel\nOnline    1546917\nRetail     947653\nName: revenue, dtype: int64\n\nAvg CAC by month:\nmonth\nDec    27.60\nNov    29.80\nOct    31.45\nName: cac, dtype: float64\n\nTotal revenue: $2,494,570\nTotal units: 11,520'
			},
			durationMs: 1870,
			phaseId: 'phase_1'
		},

		{ type: 'step', stepNumber: 1, status: 'completed', maxSteps: 8, durationMs: 5200 },

		{
			type: 'assistant',
			text: 'Data analysis complete. 450 records across 3 months (Oct-Dec 2024), 4 product categories, 4 regions, and 2 sales channels. Total Q4 revenue: $2,494,570.',
			isStreaming: false
		},

		// ── Phase 2: Build ──

		{ type: 'step', stepNumber: 2, status: 'started', maxSteps: 8 },

		{
			type: 'assistant',
			text: "The data is rich — 450 transactions across October through December with strong growth trends. Here's my plan:\n\n- **KPI cards** for total revenue ($2.49M), average CAC ($29.62), and total units (11.5K)\n- **Revenue trend** line chart showing month-over-month growth\n- **Category breakdown** doughnut chart — Electronics leads at 41.9%\n- **Regional performance** horizontal bar chart\n- **Channel comparison** (Online 62% vs Retail 38%)\n\nLet me build this out now.",
			isStreaming: false
		},

		{
			type: 'tool_call',
			callId: 'tc-003',
			toolName: 'shell',
			args: {
				action: 'exec',
				message: 'Setting up the project directory structure.',
				command: 'mkdir -p /workspace/dashboard/assets && echo "Directory created"'
			},
			status: 'success',
			result: { output: 'Directory created' },
			durationMs: 280,
			phaseId: 'phase_2'
		},

		{
			type: 'tool_call',
			callId: 'tc-004',
			toolName: 'file',
			args: {
				action: 'write',
				message: 'Creating the main HTML layout with KPI cards and chart containers.',
				path: '/workspace/dashboard/index.html'
			},
			status: 'success',
			result: {
				success: true,
				message: 'File saved: /workspace/dashboard/index.html (4.2 KB)'
			},
			durationMs: 95,
			phaseId: 'phase_2'
		},

		{
			type: 'tool_call',
			callId: 'tc-005',
			toolName: 'file',
			args: {
				action: 'write',
				message: 'Writing the stylesheet with dark theme and responsive grid layout.',
				path: '/workspace/dashboard/styles.css'
			},
			status: 'success',
			result: {
				success: true,
				message: 'File saved: /workspace/dashboard/styles.css (3.8 KB)'
			},
			durationMs: 82,
			phaseId: 'phase_2'
		},

		{
			type: 'tool_call',
			callId: 'tc-006',
			toolName: 'shell',
			args: {
				action: 'python',
				message: 'Generating the JSON data file for all chart components.',
				code_block:
					"import json, pandas as pd\n\ndf = pd.read_csv('/workspace/sales_q4.csv')\n\nmonthly = df.groupby('month').agg({'revenue': 'sum', 'cac': 'mean', 'units_sold': 'sum'}).round(2)\ncategory = df.groupby('product_category')['revenue'].sum()\nregional = df.groupby('region')['revenue'].sum()\nchannel = df.groupby('channel')['revenue'].sum()\n\ndata = {\n    'monthly': {'labels': list(monthly.index), 'revenue': list(monthly['revenue']), 'cac': list(monthly['cac']), 'units': list(monthly['units_sold'])},\n    'category': {'labels': list(category.index), 'values': list(category.values)},\n    'regional': {'labels': list(regional.index), 'values': list(regional.values)},\n    'channel': {'labels': list(channel.index), 'values': list(channel.values)},\n    'kpis': {'total_revenue': int(df['revenue'].sum()), 'avg_cac': round(df['cac'].mean(), 2), 'total_units': int(df['units_sold'].sum()), 'growth': 17.9}\n}\n\nwith open('/workspace/dashboard/data.json', 'w') as f:\n    json.dump(data, f, indent=2)\nprint('Chart data generated successfully')"
			},
			status: 'success',
			result: { output: 'Chart data generated successfully' },
			durationMs: 3100,
			phaseId: 'phase_2'
		},

		{
			type: 'tool_call',
			callId: 'tc-007',
			toolName: 'file',
			args: {
				action: 'write',
				message: 'Building the JavaScript with Chart.js for all visualizations.',
				path: '/workspace/dashboard/app.js'
			},
			status: 'success',
			result: { success: true, message: 'File saved: /workspace/dashboard/app.js (6.1 KB)' },
			durationMs: 110,
			phaseId: 'phase_2'
		},

		{
			type: 'mcp_progress',
			toolName: 'webdev',
			progress: 1,
			total: 1,
			message: 'Dev server started on port 3000'
		},

		{
			type: 'tool_call',
			callId: 'tc-008',
			toolName: 'browse',
			args: {
				message: 'Taking a screenshot to preview the initial build.',
				url: 'http://localhost:3000',
				intent: 'navigational'
			},
			status: 'success',
			result: {
				screenshot_url: '/workspace/dashboard/screenshots/preview_1.png',
				page_title: 'Q4 Sales Dashboard — Ember Analytics',
				url: 'http://localhost:3000'
			},
			durationMs: 4200,
			phaseId: 'phase_2'
		},

		{ type: 'step', stepNumber: 2, status: 'completed', maxSteps: 8, durationMs: 12400 },

		// ── HITL: theme choice ──

		{ type: 'step', stepNumber: 3, status: 'started', maxSteps: 8 },

		{
			type: 'hitl',
			requestId: 'hitl-001',
			prompt:
				"The dashboard is looking good! I've built it with a dark theme optimized for data readability. I can also offer a light, clean theme. Which do you prefer?",
			choices: ['Keep dark theme', 'Switch to light theme', 'Use system preference (auto)'],
			response: 'Keep dark theme'
		},

		{
			type: 'assistant',
			text: 'Great choice — dark themes reduce eye strain for data-heavy dashboards and make charts pop. Let me add the final polish: smooth chart animations, hover tooltips, responsive breakpoints, and some micro-interactions on the KPI cards.',
			isStreaming: false
		},

		// ── Phase 3: Polish ──

		{
			type: 'tool_call',
			callId: 'tc-009',
			toolName: 'file',
			args: {
				action: 'edit',
				path: '/workspace/dashboard/styles.css',
				old_content: '.kpi-card { padding: 1.5rem; }',
				new_content:
					'.kpi-card {\n  padding: 1.5rem;\n  transition: transform 0.2s ease, box-shadow 0.2s ease;\n}\n.kpi-card:hover {\n  transform: translateY(-2px);\n  box-shadow: 0 8px 24px rgba(0,0,0,0.12);\n}'
			},
			status: 'success',
			result: {
				success: true,
				diff: '@@ -45,1 +45,6 @@\n-.kpi-card { padding: 1.5rem; }\n+.kpi-card {\n+  padding: 1.5rem;\n+  transition: transform 0.2s ease, box-shadow 0.2s ease;\n+}\n+.kpi-card:hover {\n+  transform: translateY(-2px);\n+  box-shadow: 0 8px 24px rgba(0,0,0,0.12);\n+}'
			},
			durationMs: 150,
			phaseId: 'phase_3'
		},

		{
			type: 'tool_call',
			callId: 'tc-010',
			toolName: 'file',
			args: {
				action: 'edit',
				path: '/workspace/dashboard/app.js',
				old_content: 'animation: { duration: 0 }',
				new_content: "animation: { duration: 800, easing: 'easeOutQuart' }"
			},
			status: 'success',
			result: {
				success: true,
				diff: "@@ -12,1 +12,1 @@\n-animation: { duration: 0 }\n+animation: { duration: 800, easing: 'easeOutQuart' }"
			},
			durationMs: 130,
			phaseId: 'phase_3'
		},

		{
			type: 'tool_call',
			callId: 'tc-011',
			toolName: 'file',
			args: {
				action: 'edit',
				path: '/workspace/dashboard/styles.css',
				old_content: '@media (max-width: 768px) { }',
				new_content:
					'@media (max-width: 768px) {\n  .dashboard-grid { grid-template-columns: 1fr; }\n  .kpi-row { flex-direction: column; }\n  .chart-container { min-height: 250px; }\n}'
			},
			status: 'success',
			result: {
				success: true,
				diff: '@@ -78,1 +78,5 @@\n-@media (max-width: 768px) { }\n+@media (max-width: 768px) {\n+  .dashboard-grid { grid-template-columns: 1fr; }\n+  .kpi-row { flex-direction: column; }\n+  .chart-container { min-height: 250px; }\n+}'
			},
			durationMs: 120,
			phaseId: 'phase_3'
		},

		{
			type: 'tool_call',
			callId: 'tc-012',
			toolName: 'browse',
			args: { url: 'http://localhost:3000', intent: 'navigational' },
			status: 'success',
			result: {
				screenshot_url: '/workspace/dashboard/screenshots/polished.png',
				page_title: 'Q4 Sales Dashboard — Ember Analytics',
				url: 'http://localhost:3000'
			},
			durationMs: 3800,
			phaseId: 'phase_3'
		},

		{ type: 'step', stepNumber: 3, status: 'completed', maxSteps: 8, durationMs: 8200 },

		// ── First result ──

		{
			type: 'assistant',
			text: "Your Q4 Sales Dashboard is ready! Here's what I built:\n\n**KPI Cards** — Total revenue ($2.49M), average CAC ($29.62), total units sold (11,520), and QoQ growth (+17.9%)\n\n**Revenue Trend** — Line chart showing Oct ($756K) → Nov ($845K) → Dec ($892K) with smooth animations\n\n**Category Breakdown** — Doughnut chart: Electronics leads at 41.9%, followed by Apparel (27.2%), Home & Garden (16.5%), Sports (14.3%)\n\n**Regional Performance** — Horizontal bar chart: North ($698K), South ($612K), West ($595K), East ($589K)\n\n**Channel Split** — Online dominates at 62% ($1.55M) vs Retail at 38% ($948K)\n\nThe dashboard features hover tooltips, smooth animations, and is fully responsive down to mobile. All files are in `/workspace/dashboard/`.",
			isStreaming: false
		},

		// ──────────────────── Turn 2 ────────────────────
		{
			type: 'user',
			text: 'This looks great! Can you add a Q3 vs Q4 comparison view and export a PDF summary report?'
		},

		{ type: 'step', stepNumber: 4, status: 'started', maxSteps: 8 },

		{
			type: 'reasoning',
			text: "Two additions requested: 1) Q3 comparison overlay on existing charts to show quarter-over-quarter trends, 2) PDF export using WeasyPrint or Playwright for a printable report. I'll generate mock Q3 data with slightly lower numbers to show growth, add comparison dataset to Chart.js, then render a PDF."
		},

		{
			type: 'assistant',
			text: "I'll add the Q3 comparison and generate a PDF report. Let me process the Q3 data first.",
			isStreaming: false
		},

		{
			type: 'tool_call',
			callId: 'tc-013',
			toolName: 'shell',
			args: {
				action: 'python',
				code_block:
					"import pandas as pd, json\n\ndf_q3 = pd.read_csv('/workspace/sales_q3.csv')\ndf_q4 = pd.read_csv('/workspace/sales_q4.csv')\n\nq3_monthly = df_q3.groupby('month')['revenue'].sum()\nq4_monthly = df_q4.groupby('month')['revenue'].sum()\n\nq3_total = int(q3_monthly.sum())\nq4_total = int(q4_monthly.sum())\ngrowth = round(((q4_total - q3_total) / q3_total) * 100, 1)\n\nq3_cat = df_q3.groupby('product_category')['revenue'].sum()\nq4_cat = df_q4.groupby('product_category')['revenue'].sum()\n\ncomparison = {\n    'q3_monthly': {'labels': list(q3_monthly.index), 'values': list(map(int, q3_monthly.values))},\n    'q4_monthly': {'labels': list(q4_monthly.index), 'values': list(map(int, q4_monthly.values))},\n    'q3_total': q3_total, 'q4_total': q4_total, 'growth_pct': growth,\n    'q3_category': {'labels': list(q3_cat.index), 'values': list(map(int, q3_cat.values))},\n    'q4_category': {'labels': list(q4_cat.index), 'values': list(map(int, q4_cat.values))}\n}\n\nwith open('/workspace/dashboard/comparison.json', 'w') as f:\n    json.dump(comparison, f, indent=2)\n\nprint(f'Q3 Total: ${q3_total:,}')\nprint(f'Q4 Total: ${q4_total:,}')\nprint(f'Growth: {growth}%')"
			},
			status: 'success',
			result: {
				output: 'Q3 Total: $2,156,340\nQ4 Total: $2,494,570\nGrowth: 15.7%'
			},
			durationMs: 2800,
			phaseId: 'phase_3'
		},

		{
			type: 'tool_call',
			callId: 'tc-014',
			toolName: 'file',
			args: {
				action: 'edit',
				path: '/workspace/dashboard/app.js',
				old_content: '// Revenue trend chart',
				new_content:
					'// Revenue trend chart — with Q3 comparison overlay\n// Q3 data shown as dashed line, Q4 as solid'
			},
			status: 'success',
			result: {
				success: true,
				diff: '@@ -24,1 +24,2 @@\n-// Revenue trend chart\n+// Revenue trend chart — with Q3 comparison overlay\n+// Q3 data shown as dashed line, Q4 as solid'
			},
			durationMs: 140,
			phaseId: 'phase_3'
		},

		{
			type: 'tool_call',
			callId: 'tc-015',
			toolName: 'file',
			args: { action: 'read', path: '/workspace/dashboard/index.html' },
			status: 'success',
			result: {
				content:
					'<!DOCTYPE html>\n<html lang="en">\n<head>\n  <meta charset="UTF-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n  <title>Q4 Sales Dashboard — Ember Analytics</title>\n  <link rel="stylesheet" href="styles.css">\n  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>\n</head>\n<body>\n  <div class="dashboard">\n    <header class="dashboard-header">\n      <h1>Q4 Sales Performance</h1>\n      <span class="subtitle">Oct — Dec 2024</span>\n    </header>\n    <div class="kpi-row">...</div>\n    <div class="dashboard-grid">...</div>\n  </div>\n  <script src="app.js"></script>\n</body>\n</html>',
				path: '/workspace/dashboard/index.html',
				size: 4218
			},
			durationMs: 45,
			phaseId: 'phase_3'
		},

		{
			type: 'tool_call',
			callId: 'tc-016',
			toolName: 'file',
			args: {
				action: 'edit',
				path: '/workspace/dashboard/index.html',
				old_content: '<span class="subtitle">Oct — Dec 2024</span>',
				new_content:
					'<span class="subtitle">Oct — Dec 2024</span>\n      <div class="comparison-badge">+15.7% vs Q3</div>'
			},
			status: 'success',
			result: {
				success: true,
				diff: '@@ -14,1 +14,2 @@\n       <span class="subtitle">Oct — Dec 2024</span>\n+      <div class="comparison-badge">+15.7% vs Q3</div>'
			},
			durationMs: 110,
			phaseId: 'phase_3'
		},

		{ type: 'step', stepNumber: 4, status: 'completed', maxSteps: 8, durationMs: 7200 },
		{ type: 'step', stepNumber: 5, status: 'started', maxSteps: 8 },

		{
			type: 'tool_call',
			callId: 'tc-017',
			toolName: 'browse',
			args: { url: 'http://localhost:3000', intent: 'navigational' },
			status: 'success',
			result: {
				screenshot_url: '/workspace/dashboard/screenshots/comparison_view.png',
				page_title: 'Q4 Sales Dashboard — Ember Analytics',
				url: 'http://localhost:3000'
			},
			durationMs: 3900,
			phaseId: 'phase_3'
		},

		{
			type: 'assistant',
			text: 'Comparison view looks great — the Q3 trend line overlays nicely. Now generating the PDF report.',
			isStreaming: false
		},

		{
			type: 'tool_call',
			callId: 'tc-018',
			toolName: 'shell',
			args: {
				action: 'python',
				code_block:
					"from weasyprint import HTML\nimport datetime\n\nhtml = open('/workspace/dashboard/index.html').read()\ncss = open('/workspace/dashboard/styles.css').read()\n\n# Inject print-friendly overrides\nprint_css = css + '''\n@media print {\n  body { background: white; color: #1a1a1a; }\n  .chart-container { break-inside: avoid; }\n}\n'''\n\nHTML(string=html, base_url='/workspace/dashboard/').write_pdf(\n    '/workspace/dashboard/Q4_Sales_Report.pdf',\n    stylesheets=['/workspace/dashboard/styles.css']\n)\n\nprint(f'PDF generated: Q4_Sales_Report.pdf')\nprint(f'Timestamp: {datetime.datetime.now().strftime(\"%Y-%m-%d %H:%M\")}')"
			},
			status: 'success',
			result: {
				output: 'PDF generated: Q4_Sales_Report.pdf\nTimestamp: 2024-12-18 14:32'
			},
			durationMs: 5600,
			phaseId: 'phase_3'
		},

		{
			type: 'tool_call',
			callId: 'tc-019',
			toolName: 'file',
			args: { action: 'view', path: '/workspace/dashboard' },
			status: 'success',
			result: {
				entries: [
					{ name: 'index.html', type: 'file', size: 4218 },
					{ name: 'styles.css', type: 'file', size: 3812 },
					{ name: 'app.js', type: 'file', size: 6144 },
					{ name: 'data.json', type: 'file', size: 1024 },
					{ name: 'comparison.json', type: 'file', size: 856 },
					{ name: 'Q4_Sales_Report.pdf', type: 'file', size: 284672 },
					{ name: 'assets', type: 'directory' },
					{ name: 'screenshots', type: 'directory' }
				],
				path: '/workspace/dashboard',
				total: 8
			},
			durationMs: 35,
			phaseId: 'phase_3'
		},

		{ type: 'step', stepNumber: 5, status: 'completed', maxSteps: 8, durationMs: 11200 },

		// ── Final result ──

		{
			type: 'assistant',
			text: "All done! Here's what I added:\n\n**Q3 vs Q4 Comparison**\n- Revenue grew **15.7%** quarter-over-quarter ($2.16M → $2.49M)\n- Dashed Q3 trend line overlaid on the revenue chart\n- Every month outperformed Q3: Oct +14.2%, Nov +16.1%, Dec +16.8%\n- New comparison badge in the dashboard header\n\n**PDF Report** (`Q4_Sales_Report.pdf`, 278 KB)\n- All KPIs, charts, and comparison data in a print-ready format\n- Optimized for A4 with page break handling\n- Ready to share with stakeholders\n\nAll files are in `/workspace/dashboard/`. The dev server is still running at `localhost:3000` if you want to keep iterating.",
			isStreaming: false
		}
	];

	// ── Build tool calls map ──
	const tcMap = new Map<string, ToolCallMsg>();
	for (const msg of mockMessages) {
		if (msg.type === 'tool_call') {
			tcMap.set(msg.callId, msg);
		}
	}

	// ── Plan state (all phases completed) ──
	const plan: PlanState = {
		goal: 'Build a Q4 sales performance dashboard with interactive visualizations',
		phases: [
			{
				id: 'phase_1',
				description: 'Analyze CSV data and understand structure',
				status: 'completed',
				startedAt: '2024-12-18T14:00:00Z',
				completedAt: '2024-12-18T14:01:12Z'
			},
			{
				id: 'phase_2',
				description: 'Build dashboard layout, charts, and KPI cards',
				status: 'completed',
				startedAt: '2024-12-18T14:01:12Z',
				completedAt: '2024-12-18T14:04:30Z'
			},
			{
				id: 'phase_3',
				description: 'Polish, add Q3 comparison, and export PDF',
				status: 'completed',
				startedAt: '2024-12-18T14:04:30Z',
				completedAt: '2024-12-18T14:07:15Z'
			}
		],
		currentPhaseId: 'phase_3'
	};

	// ── Set all stores ──
	messages.set(mockMessages);
	toolCalls.set(tcMap);
	planState.set(plan);
	runStatus.set('completed');
	activeStep.set({ stepNumber: 5, status: 'completed', maxSteps: 8, durationMs: 11200 });
	tokenUsage.set({
		inputTokens: 24560,
		outputTokens: 8930,
		totalTokens: 33490,
		model: 'claude-sonnet-4-6'
	});
}
