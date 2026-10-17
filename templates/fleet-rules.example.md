<!--
  Example of the install-local fleet rules file (FLEETRULES1013).

  The real file is store/fleet-rules.md, which is gitignored like the root
  CLAUDE.md it is copied from: it names the owner, the companies, which agent
  holds which live access and the incident authorizations, none of which belongs
  in a versioned file. This example carries no rules on purpose.

  How it is used: for an agent whose agent-config.json sets
  "excludeRootClaudeMd": true, ensureFleetRulesSection() (src/web/agent-scaffold.ts)
  renders store/fleet-rules.md into the agent's CLAUDE.md as a generated block,
  and only then adds the root CLAUDE.md to claudeMdExcludes in the agent's
  .claude/settings.json. Put here every rule of the root CLAUDE.md that a
  sub-agent needs and does not already carry in its own file.

  Placeholders: {{AGENT_ID}}, {{PROJECT_ROOT}}, {{DASHBOARD_ORIGIN}}.

  Building it: node scripts/fleet-rules-sync.mjs rebuilds this file from the root
  CLAUDE.md and store/fleet-rules-map.json (templates/fleet-rules-map.example.json)
  and stamps it; a root section the map does not classify stops the sync.

  Drift gate: the exclusion only applies while this comment carries the sha256 of
  the current root CLAUDE.md. After syncing the rules, stamp them:
    node scripts/fleet-rules-stamp.mjs          (writes synced-from-root-sha256=...)
    node scripts/fleet-rules-stamp.mjs --check  (exit 1 when the root has changed)
  Until then the root CLAUDE.md stays loaded and the block is not written.
-->

## Example section

Rules for {{AGENT_ID}} go here, copied from the root CLAUDE.md.
