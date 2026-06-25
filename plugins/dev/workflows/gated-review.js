/**
 * Gated review: drive an artifact to "clean" through dev-adversarial-review.
 *
 * The concrete form of autonomous-feature's Phase 2/4/6 loop. Each round runs the
 * `dev-adversarial-review` workflow (nested one level), and if surviving blocker/major
 * findings remain, dispatches a fix agent to address them, then re-reviews the
 * revised artifact. Caps at 3 rounds.
 *
 * Returns one of:
 *   { clean: true,  rounds, history, review }                  // converged
 *   { clean: false, needsHuman: true, rounds, history, contested, review }  // hit the cap
 *
 * It never pings the human itself (workflows are headless). The PING CONTRACT
 * (premise-breaking / security / scope findings) stays with the caller: it reads
 * the returned `review.findings` and decides what stops the pipeline. This wrapper
 * owns only the convergence loop and the cap.
 *
 * args: same shape as dev-adversarial-review, plus:
 *   maxRounds?: number   // default 3
 *   fixConventions?: string  // optional repo conventions handed to the fix agent
 *
 * NOTE: the fix step MUTATES the artifact (edits the doc, or code in repoDir). For
 * a diff whose range is two committed branches, the fix agent must commit for the
 * change to re-appear in that range; in autonomous-feature the coordinator owns
 * the worktree and verification around this. Do not run this on a tree you are not
 * prepared to have edited.
 */
export const meta = {
  name: 'dev-gated-review',
  description:
    'Drive an artifact to clean through dev-adversarial-review: review, fix, re-review, capped at 3 rounds. Returns clean, or the contested findings for a human when it does not converge.',
  phases: [
    { title: 'Gate', detail: 'review -> fix -> re-review until clean or capped' },
  ],
}

const a = typeof args === 'string' ? JSON.parse(args) : args || {}
const MAX_ROUNDS = a.maxRounds || 3

function fixPrompt(art, blockers, round) {
  const target =
    art.artifactType === 'diff'
      ? `the code under ${art.repoDir || 'the repo'} (the diff ${art.diffRange || ''})`
      : `the ${art.artifactType} at ${art.artifactPath}`
  const items = blockers
    .map((f, i) => `${i + 1}. [${f.severity}] ${f.objection}\n   Location: ${f.location}\n   Suggested fix: ${f.suggested_fix}`)
    .join('\n\n')
  const conventions = art.fixConventions ? `\n\nFollow these conventions: ${art.fixConventions}` : ''
  return `Round ${round} fix pass. Address ONLY these confirmed blocker/major findings in ${target}, making the smallest change that resolves each. Do not refactor beyond them and do not touch anything out of scope.${conventions}

${items}

When done, briefly state per finding what you changed (or why it was already handled). A later re-review will check your work, so do not claim a fix you did not make.`
}

const history = []
let round = 0
let review = null

while (true) {
  round += 1
  phase(`Round ${round}`)
  // Nested one level: dev-gated-review is top-level, dev-adversarial-review is the child.
  review = await workflow('dev-adversarial-review', a)
  history.push({
    round,
    findings: review.findings.length,
    refuted: (review.refuted || []).length,
    hasBlockerOrMajor: review.hasBlockerOrMajor,
  })

  if (!review.hasBlockerOrMajor) {
    log(`Round ${round}: clean, no surviving blocker/major.`)
    return { clean: true, rounds: round, history, review }
  }

  const blockers = review.findings.filter((f) => f.severity !== 'minor')
  if (round >= MAX_ROUNDS) {
    log(`Round ${round}: cap reached with ${blockers.length} unresolved blocker/major; escalating to human.`)
    return { clean: false, needsHuman: true, rounds: round, history, contested: blockers, review }
  }

  log(`Round ${round}: ${blockers.length} blocker/major remain; dispatching fix pass.`)
  // Edits IN PLACE (no worktree isolation) so the next round re-reviews the real
  // result; rounds are sequential, so there are no cross-agent file races. The fix
  // agent needs write tools. In autonomous-feature the coordinator runs this whole
  // loop inside one worktree, so isolation is handled there, not per fix agent.
  await agent(fixPrompt(a, blockers, round), {
    label: `fix:round${round}`,
    phase: `Round ${round}`,
    model: 'opus',
  })
}
