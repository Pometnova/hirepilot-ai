HirePilot AI — Overview UI Redesign
Objective
Redesign the existing Streamlit application to closely match the approved visual reference screenshot.
This is a UI-only redesign. Preserve all existing backend functionality, MCP tools, Claude API integration, recruiting agent logic, database queries, and tests.
Do not rebuild the application or introduce another framework.
1. Visual Reference
Use the approved screenshot as the primary visual reference.
Preserve its overall composition:
Narrow, dark-purple navigation sidebar on the left.
Spacious, light-colored recruiting dashboard in the center.
Dark-purple header and light conversation area for the AI Assistant on the right.
Large "Recruiting Overview" heading.
Compact KPI cards.
Thin borders, restrained shadows and consistent spacing.
Professional enterprise SaaS appearance.
Do not substitute a different dashboard layout.
2. Branding
Product name: HirePilot AI
Use the two previously approved original HirePilot AI logo designs, supplied separately as image assets.
Primary horizontal logo: sidebar/header.
Secondary expressive logo: optional welcome screen or presentation.
Small standalone brand icon: AI assistant avatar, if a suitable asset exists.
Never use or reproduce any logo shown in the mockup screenshot.
Color palette:
Sidebar / dark purple: #211747
Primary text: #201936
Coral accent: #FF674C
Secondary purple: #75619B
Light lavender: #E9E3F2
Main background: #FAF9F8
Card background: #FFFFFF
Secondary text: #777384
Use Inter or a visually similar sans-serif font. Use restrained monospace typography for technical metadata where appropriate.
Charts must share the same purple/lavender/coral visual system.
3. Main Layout
Use Streamlit wide layout.
Left Sidebar
Include:
HirePilot AI logo
Overview
Ask AI
Candidates
Tasks
Only show navigation destinations that are actually implemented. Do not create nonfunctional pages.
Active navigation item uses a subtle purple background and coral accent.
Main Header
Display:
Quillfeather Labs
Data as of October 15, 2026
Recruiting Overview
Subtitle: "Track progress. Find insights. Make data-driven hiring decisions."
Keep the title large, similar to the reference screenshot.
KPI Row
Four horizontally aligned metrics:
Overdue Tasks
Pending Scorecards
Unanswered Emails
Upcoming Offer Deadlines
All numbers must be computed from existing data.
Where supported, clicking a KPI filters or reveals corresponding task records.
Open Positions
Show three existing roles:
Backend Engineer
Product Designer
Customer Success Manager
Display applicant counts and meaningful pipeline information.
Do not use misleading completion percentages based solely on stage numbers.
Clicking a role should update the selected role filter.
Priority Actions
Display actionable task records:
Overdue first
Due today
Pending
No due date
Show task type, candidate or role, deadline and status.
Explicitly distinguish assumed deadlines from source-provided deadlines.
Recruitment Analytics
Render existing Plotly charts:
Recruitment Funnel
Horizontal bars
X: unique application count
Y: stages in pipeline order
Days in Stage
X: median days
Y: stage
Highlight bottlenecks using coral
Candidate Ranking Breakdown
Show in relevant AI answers
Missing scores must remain unmeasured
Tasks by Due Date
Show task counts by deadline category
All charts must share consistent typography, axes, background and colors.
Reuse existing Python-computed chart data.
Data Quality
Show a compact summary of detected data issues.
Allow users to expand details with source references.
Do not count every missing scorecard as a data corruption issue; distinguish incomplete feedback from actual record conflicts.
Recent Activity
Include only if the existing data layer supports it without additional substantial work.
Do not invent relative timestamps. All dates must respect the dataset export date.
4. AI Assistant — Right Panel
Preserve the right-side panel layout from the reference screenshot.
Panel sections:
Ask AI / Insights heading
Recruiting Intelligence introduction
Three suggested questions
Conversation area
Chat input
Suggested questions:
Who are the top 3 candidates for [selected role], and why?
Where is our hiring process losing candidates?
Which tasks are pending or overdue?
Suggested questions must invoke the existing recruiting agent, not static responses.
The AI Assistant must support follow-up questions and conversational context.
For long answers, provide access to the full Ask AI workspace.
AI Response Presentation
Responses should visually distinguish:
FACTS — source-backed findings
AI ASSESSMENT — evidence-based interpretation
ASSUMPTIONS — explicitly labeled
SOURCES — file names and record IDs
CHARTS — rendered from existing Python chart data
Do not expose private chain-of-thought reasoning. Display concise explanations, evidence, comparisons and recommendations instead.
Missing scorecards are not negative feedback.
5. Interactions
Role selection updates relevant dashboard data.
KPI selection reveals matching tasks.
Suggested questions invoke the existing agent.
Chat supports follow-up questions.
Chart tooltips display useful values and denominators.
Source references remain visible.
Dashboard filters do not trigger paid LLM calls.
Only AI requests invoke the LLM.
6. Streamlit Implementation Constraints
Use existing Streamlit components, Plotly and lightweight CSS.
Prefer:
st.columns
st.container
st.metric or styled metric containers
st.selectbox
st.expander
st.plotly_chart
st.chat_input
st.session_state
Do not force a fixed right-side chat panel using fragile CSS if it breaks Streamlit reruns or chat input behavior.
If necessary, use a compact AI preview panel on Overview and the full working chat in Ask AI.
Do not introduce React, a separate frontend or unnecessary dependencies.
7. Acceptance Criteria
The interface closely resembles the approved screenshot.
Existing functionality remains operational.
Both Dashboard and Ask AI use the same underlying data.
All metrics and charts reflect real records.
LLM responses contain evidence and source references.
Role filters and task interactions work.
The interface remains usable at common desktop widths.
Never use or reproduce any logo shown in the mockup screenshot.
Existing tests continue to pass.
Implementation Order
Inspect existing Streamlit UI files and identify reusable components.
Implement theme, typography, sidebar and page layout.
Restyle KPI cards and existing dashboard sections.
Apply consistent Plotly styling.
Integrate the existing AI Assistant into the approved layout.
Verify interactions and data accuracy.
Run existing tests.
Keep the implementation focused on visual improvements. Avoid unrelated refactoring.
