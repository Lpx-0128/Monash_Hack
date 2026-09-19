# Dashboard refinement

## Agreed direction

Apricot / terracotta, with dark brown text. The primary user is a shipping documentation coordinator checking a draft BL against SI. The overview remains comprehensive, with filters; a dedicated case workspace prioritizes unresolved fields, evidence, and decisions.

Core colors: canvas `#F4DDC8`, panels `#FCEBDC`, primary text `#352419`, secondary text `#70523E`, primary action `#A04420` with white text. Success, uncertainty, discrepancy, and failure retain labeled semantic status colors.

## Adapted bookmark patterns

- **Efferd Dashboard 2:** consistent navigation, aligned summary panels, clear separation between the operational overview and case work.
- **Glassmorphism Minimal Metrics:** restrained translucent gradients, inset highlights, and subtle depth on metrics. Text remains fully opaque.
- **Animated Table rows:** short entrance translation and hover feedback. No opacity animation; reduced-motion preferences disable motion.
- **AI Agent Pipeline:** a compact case-progress sequence backed by current-run history and workflow state. Recorded milestones are distinguished from missing events; completion never substitutes for external correction, human input, or failure.

## Preserved behavior

The API, document links, source provenance, decision preview and confirmation, stale-run recovery, replay, polling, machine-assessment immutability, operational outcome, and activity history are unchanged. No Telegram delivery is triggered by the new UI.

The overview adds local search, email category, and overlapping review-state filters. A known field mismatch remains discoverable even if another field needs human input. Matched cases require a completed BL comparison with operational OK; general correspondence is not described as a document match.

Within a case, unresolved fields and human-applied values remain visible. Routine matching fields collapse into an expandable section, retaining their full values and evidence. Human-applied values remain visible after resumption so the user can verify the accepted result.

Operational insights and synthetic email context remain available in expandable sections. The design does not infer the authoritative document across email revisions or add a new business action.

## Verification

Run `npm run build`, `npm test`, and `npx playwright test` against a local simulator at port 5173. The refinement browser checks cover overview filtering, issue-first comparison, real progress states, reduced motion, responsive overflow, and axe accessibility. Existing browser journeys verify decisions and recovery; F2/F3 browser tests use Telegram transport doubles rather than sending messages.
