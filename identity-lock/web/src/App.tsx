/**
 * The dashboard.
 *
 * A viewer, not a control panel: it reads runs the CLI already produced. Every
 * number shown here is the number stored in `run.json`, formatted — nothing is
 * recomputed in the browser, so the dashboard and the HTML report can never
 * disagree about what a run measured.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { JSX } from 'react'
import {
  api,
  type Candidate,
  type ComparisonDetail,
  type ComparisonSummary,
  type Gate,
  type Health,
  type RunDetail,
  type RunSummary,
} from './api'
import { DeltaBars, DriftChart, Scatter } from './charts'

type Selection = { kind: 'run'; id: string } | { kind: 'comparison'; id: string } | null
type Filter = 'all' | 'accepted' | 'rejected' | 'shortlist'
type SortKey = 'order' | 'identity' | 'technical' | 'margin'

const signed = (value: number, digits = 3): string => `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`

function Pill({ ok, children }: { ok: boolean; children: React.ReactNode }): JSX.Element {
  return <span className={ok ? 'pill ok' : 'pill bad'}>{children}</span>
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }): JSX.Element {
  return (
    <div className="stat">
      <div className="k">{label}</div>
      <div className="v">{value}</div>
      {note ? <div className="n">{note}</div> : null}
    </div>
  )
}

function Gates({ gates }: { gates: Gate[] }): JSX.Element {
  return (
    <table>
      <thead>
        <tr>
          <th />
          <th>gate</th>
          <th className="num">observed</th>
          <th className="num">threshold</th>
          <th>what it means</th>
        </tr>
      </thead>
      <tbody>
        {gates.map((gate) => (
          <tr key={gate.name}>
            <td>
              <Pill ok={gate.passed}>{gate.passed ? 'pass' : 'fail'}</Pill>
            </td>
            <td>
              <code>{gate.name}</code>
            </td>
            <td className="num">{gate.observed === null ? '—' : gate.observed.toFixed(4)}</td>
            <td className="num">{gate.threshold === null ? '—' : gate.threshold.toFixed(4)}</td>
            <td className="muted">{gate.detail}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function CandidateCard({
  candidate,
  onOpen,
}: {
  candidate: Candidate
  onOpen: (candidate: Candidate) => void
}): JSX.Element {
  const classes = ['card']
  if (candidate.decision === 'reject') classes.push('rejected')
  if (candidate.selected) classes.push('selected')
  return (
    <button type="button" className={classes.join(' ')} onClick={() => onOpen(candidate)}>
      {candidate.image ? <img src={candidate.image} alt={candidate.id} loading="lazy" /> : <div className="noimage" />}
      <div className="meta">
        <Pill ok={candidate.decision === 'accept'}>{candidate.decision === 'accept' ? 'accepted' : 'rejected'}</Pill>
        {candidate.selected ? <span className="pill warn">shortlist</span> : null}
        <div className="line">
          <code>{candidate.prompt_id}</code> · seed {candidate.seed}
        </div>
        <div className="line">
          id <b>{signed(candidate.metrics.identity_similarity)}</b> · tech{' '}
          <b>{candidate.metrics.technical_score.toFixed(3)}</b>
        </div>
        {candidate.rejections.length > 0 ? <div className="why">{candidate.rejections.join('; ')}</div> : null}
      </div>
    </button>
  )
}

function CandidateDialog({ candidate, onClose }: { candidate: Candidate; onClose: () => void }): JSX.Element {
  useEffect(() => {
    const handler = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const metrics = candidate.metrics
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label={candidate.id} onClick={onClose}>
      <div className="dialog" onClick={(event) => event.stopPropagation()}>
        {candidate.image ? <img src={candidate.image} alt={candidate.id} /> : null}
        <div className="dialog-body">
          <h3>{candidate.id}</h3>
          <p className="muted">{candidate.prompt}</p>
          <dl>
            <div>
              <dt>identity</dt>
              <dd>{signed(metrics.identity_similarity, 4)}</dd>
            </div>
            <div>
              <dt>nearest reference</dt>
              <dd>{signed(metrics.nearest_reference, 4)}</dd>
            </div>
            <div>
              <dt>impostor margin</dt>
              <dd>
                {metrics.identity_margin === null ? '—' : signed(metrics.identity_margin, 4)}
                {metrics.impostor_id ? <span className="muted"> vs {metrics.impostor_id}</span> : null}
              </dd>
            </div>
            <div>
              <dt>technical</dt>
              <dd>{metrics.technical_score.toFixed(4)}</dd>
            </div>
            <div>
              <dt>sharpness / exposure / contrast</dt>
              <dd>
                {metrics.frame.sharpness.toFixed(3)} / {metrics.frame.exposure.toFixed(3)} /{' '}
                {metrics.frame.contrast.toFixed(3)}
              </dd>
            </div>
            <div>
              <dt>frame</dt>
              <dd>
                {metrics.frame.width}×{metrics.frame.height}
              </dd>
            </div>
          </dl>
          {candidate.rejections.length > 0 ? (
            <p className="why">Rejected: {candidate.rejections.join('; ')}</p>
          ) : null}
          <button type="button" className="ghost" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

function RunView({ run }: { run: RunDetail }): JSX.Element {
  const [filter, setFilter] = useState<Filter>('all')
  const [sort, setSort] = useState<SortKey>('order')
  const [open, setOpen] = useState<Candidate | null>(null)

  const identityGate = run.gates.find((gate) => gate.name === 'identity_p05')
  const threshold = useMemo(() => {
    const rejected = run.candidates
      .filter((item) => item.decision === 'reject' && item.rejections.some((r) => r.startsWith('identity')))
      .map((item) => item.metrics.identity_similarity)
    const accepted = run.candidates
      .filter((item) => item.decision === 'accept')
      .map((item) => item.metrics.identity_similarity)
    // The candidate threshold is not stored on the run; it sits strictly between
    // the worst accepted frame and the best frame rejected *for identity*.
    if (rejected.length > 0 && accepted.length > 0) return (Math.max(...rejected) + Math.min(...accepted)) / 2
    return identityGate?.threshold ?? Math.min(...run.candidates.map((c) => c.metrics.identity_similarity))
  }, [run, identityGate])

  const visible = useMemo(() => {
    const filtered = run.candidates.filter((item) => {
      if (filter === 'accepted') return item.decision === 'accept'
      if (filter === 'rejected') return item.decision === 'reject'
      if (filter === 'shortlist') return item.selected
      return true
    })
    const key = (item: Candidate): number => {
      if (sort === 'identity') return -item.metrics.identity_similarity
      if (sort === 'technical') return -item.metrics.technical_score
      if (sort === 'margin') return -(item.metrics.identity_margin ?? 0)
      return 0
    }
    return sort === 'order' ? filtered : [...filtered].sort((a, b) => key(a) - key(b))
  }, [run, filter, sort])

  const aggregates = run.aggregates
  const identity = run.candidates.map((item) => item.metrics.identity_similarity)
  const technical = run.candidates.map((item) => item.metrics.technical_score)
  const accepted = run.candidates.map((item) => item.decision === 'accept')
  const technicalThreshold = useMemo(() => {
    const bad = run.candidates
      .filter((item) => item.rejections.some((r) => r.startsWith('technical')))
      .map((item) => item.metrics.technical_score)
    const good = run.candidates
      .filter((item) => !item.rejections.some((r) => r.startsWith('technical')))
      .map((item) => item.metrics.technical_score)
    if (bad.length > 0 && good.length > 0) return (Math.max(...bad) + Math.min(...good)) / 2
    return undefined
  }, [run])

  return (
    <>
      <header className="detail-head">
        <div>
          <h2>{run.character.name}</h2>
          <p className="muted">
            {run.label} · suite <code>{run.suite_id}</code> · recipe <code>{run.recipe.revision}</code>
          </p>
        </div>
        <a className="ghost" href={`api/runs/${encodeURIComponent(run.run_id)}/report`} target="_blank" rel="noreferrer">
          Open static report
        </a>
      </header>

      <div className={run.passed ? 'verdict' : 'verdict fail'}>
        <span className="tag">{run.passed ? 'PASS' : 'FAIL'}</span>
        <span className="muted">
          {run.passed ? 'Every gate cleared.' : `Failed gates: ${run.failed_gates.join(', ')}.`}
        </span>
      </div>

      <div className="stats">
        <Stat
          label="identity (mean)"
          value={signed(aggregates.identity_mean)}
          note={`95% CI [${signed(aggregates.identity_ci_low)}, ${signed(aggregates.identity_ci_high)}]`}
        />
        <Stat label="identity p05" value={signed(aggregates.identity_p05)} note={`min ${signed(aggregates.identity_min)}`} />
        <Stat
          label="impostor margin"
          value={aggregates.margin_mean === null ? '—' : signed(aggregates.margin_mean)}
          note="mean over the cohort"
        />
        <Stat
          label="consistency"
          value={`${Math.round(aggregates.consistency_rate * 100)}%`}
          note={`${aggregates.n_accepted}/${aggregates.n_total} accepted`}
        />
        <Stat label="technical" value={aggregates.technical_mean.toFixed(3)} note="sharpness / exposure / contrast" />
        <Stat
          label="drift per 10"
          value={signed(aggregates.drift_slope, 4)}
          note={`p=${aggregates.drift_p_value.toFixed(3)}, R²=${aggregates.drift_r2.toFixed(2)}`}
        />
        <Stat label="diversity" value={aggregates.diversity.toFixed(3)} note="mean pairwise content distance" />
        <Stat label="shortlist" value={String(run.n_selected)} note="MMR over accepted takes" />
      </div>

      <h3 className="section">Gates</h3>
      <div className="panel">
        <Gates gates={run.gates} />
      </div>

      <h3 className="section">Identity across the batch</h3>
      <div className="chart-row">
        <div className="chartcard wide">
          <h4>Identity by position</h4>
          <p className="muted">
            Prompts are interleaved, so a slope is degradation over the batch rather than the prompt list
            running out of easy shots.
          </p>
          <DriftChart values={identity} accepted={accepted} threshold={threshold} slopePer10={aggregates.drift_slope} />
        </div>
        <div className="chartcard">
          <h4>Identity against technical quality</h4>
          <p className="muted">Two independent ways to fail; the shaded quadrant clears both gates.</p>
          <Scatter
            xs={identity}
            ys={technical}
            accepted={accepted}
            xThreshold={threshold}
            yThreshold={technicalThreshold}
            xLabel="identity"
            yLabel="technical"
          />
        </div>
      </div>

      <h3 className="section">
        Takes
        <span className="controls">
          {(['all', 'accepted', 'rejected', 'shortlist'] as Filter[]).map((value) => (
            <button
              key={value}
              type="button"
              className={filter === value ? 'chip active' : 'chip'}
              onClick={() => setFilter(value)}
            >
              {value}
            </button>
          ))}
          <select value={sort} onChange={(event) => setSort(event.target.value as SortKey)} aria-label="sort takes">
            <option value="order">batch order</option>
            <option value="identity">identity</option>
            <option value="technical">technical</option>
            <option value="margin">margin</option>
          </select>
        </span>
      </h3>
      <div className="gallery">
        {visible.map((candidate) => (
          <CandidateCard key={candidate.id} candidate={candidate} onOpen={setOpen} />
        ))}
      </div>
      {visible.length === 0 ? <p className="muted">No takes match this filter.</p> : null}

      <h3 className="section">Provenance</h3>
      <div className="panel meta-list">
        <div>
          <span>run id</span>
          <span>
            <code>{run.run_id}</code>
          </span>
        </div>
        <div>
          <span>generated</span>
          <span>{new Date(run.created_at).toLocaleString()}</span>
        </div>
        <div>
          <span>embedder</span>
          <span>
            <code>{run.embedder}</code>
          </span>
        </div>
        <div>
          <span>provider</span>
          <span>
            <code>{run.provider}</code>
          </span>
        </div>
        <div>
          <span>cohort</span>
          <span>{run.suite.cohort_ids.join(', ')}</span>
        </div>
        <div>
          <span>disclosure</span>
          <span>{run.character.disclosure}</span>
        </div>
      </div>

      {open ? <CandidateDialog candidate={open} onClose={() => setOpen(null)} /> : null}
    </>
  )
}

function ComparisonView({ comparison }: { comparison: ComparisonDetail }): JSX.Element {
  const deltas = comparison.pairs.map((pair) => pair.delta)
  const labels = comparison.pairs.map((pair) => `${pair.prompt_id} · seed ${pair.seed}`)
  const tone =
    comparison.outcome === 'improvement' ? 'verdict' : comparison.outcome === 'regression' ? 'verdict fail' : 'verdict warn'

  return (
    <>
      <header className="detail-head">
        <div>
          <h2>
            {comparison.challenger_label} <span className="muted">vs</span> {comparison.baseline_label}
          </h2>
          <p className="muted">
            Paired A/B on <code>{comparison.metric}</code> · {comparison.n_pairs} cells · same prompts, same seeds.
          </p>
        </div>
      </header>

      <div className={tone}>
        <span className="tag">{comparison.outcome.toUpperCase()}</span>
        <span className="muted">{comparison.rationale}</span>
      </div>

      <div className="stats">
        <Stat label="win rate" value={`${Math.round(comparison.win_rate * 100)}%`} note={`${comparison.n_pairs} cells`} />
        <Stat label="mean delta" value={signed(comparison.mean_delta, 4)} note="challenger − baseline" />
        <Stat
          label="95% CI"
          value={`[${signed(comparison.ci_low, 4)}, ${signed(comparison.ci_high, 4)}]`}
          note="percentile bootstrap"
        />
        <Stat label="effect size" value={signed(comparison.effect_size)} note="matched-pairs rank-biserial" />
      </div>

      <h3 className="section">Every paired cell</h3>
      <div className="chartcard wide">
        <p className="muted">
          The shaded band is the confidence interval for the mean difference. When it crosses zero the comparison
          is inconclusive, however the bars look.
        </p>
        <DeltaBars deltas={deltas} labels={labels} ci={[comparison.ci_low, comparison.ci_high]} />
      </div>

      <h3 className="section">Gates</h3>
      <div className="panel">
        <Gates gates={comparison.gates} />
      </div>
    </>
  )
}

export function App(): JSX.Element {
  const [health, setHealth] = useState<Health | null>(null)
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [comparisons, setComparisons] = useState<ComparisonSummary[]>([])
  const [selection, setSelection] = useState<Selection>(null)
  const [run, setRun] = useState<RunDetail | null>(null)
  const [comparison, setComparison] = useState<ComparisonDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.health(), api.runs(), api.comparisons()])
      .then(([healthPayload, runsPayload, comparisonsPayload]) => {
        setHealth(healthPayload)
        setRuns(runsPayload)
        setComparisons(comparisonsPayload)
        const first = runsPayload[0]
        if (first) setSelection({ kind: 'run', id: first.run_id })
      })
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)))
  }, [])

  useEffect(() => {
    if (!selection) return
    setError(null)
    if (selection.kind === 'run') {
      setComparison(null)
      api.run(selection.id).then(setRun).catch((cause: unknown) => setError(String(cause)))
    } else {
      setRun(null)
      api.comparison(selection.id).then(setComparison).catch((cause: unknown) => setError(String(cause)))
    }
  }, [selection])

  const select = useCallback((next: Selection) => setSelection(next), [])

  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <strong>Identity Lock</strong>
          <span className="muted">{health ? `v${health.version}` : ''}</span>
        </div>
        <p className="muted small">
          {health ? `${health.runs} runs · ${health.comparisons} comparisons` : 'loading…'}
        </p>

        <h4>Runs</h4>
        <ul>
          {runs.map((item) => (
            <li key={item.run_id}>
              <button
                type="button"
                className={selection?.kind === 'run' && selection.id === item.run_id ? 'nav active' : 'nav'}
                onClick={() => select({ kind: 'run', id: item.run_id })}
              >
                <Pill ok={item.passed}>{item.passed ? 'pass' : 'fail'}</Pill>
                <span className="nav-label">{item.recipe.name}</span>
                <span className="muted small">{signed(item.aggregates.identity_mean)}</span>
              </button>
            </li>
          ))}
        </ul>

        <h4>Comparisons</h4>
        <ul>
          {comparisons.map((item) => (
            <li key={item.comparison_id}>
              <button
                type="button"
                className={
                  selection?.kind === 'comparison' && selection.id === item.comparison_id ? 'nav active' : 'nav'
                }
                onClick={() => select({ kind: 'comparison', id: item.comparison_id })}
              >
                <span className={`pill ${item.outcome === 'improvement' ? 'ok' : item.outcome === 'regression' ? 'bad' : 'warn'}`}>
                  {item.outcome.slice(0, 4)}
                </span>
                <span className="nav-label">
                  {item.metric} <span className="muted">vs {item.baseline_run_id.split('.').pop()}</span>
                </span>
                <span className="muted small">{signed(item.mean_delta, 3)}</span>
              </button>
            </li>
          ))}
        </ul>

        <footer className="muted small">
          All imagery is AI-generated. The characters are openly virtual and depict no real person.
        </footer>
      </aside>

      <main>
        {error ? <div className="verdict fail"><span className="tag">ERROR</span><span>{error}</span></div> : null}
        {run ? <RunView run={run} /> : null}
        {comparison ? <ComparisonView comparison={comparison} /> : null}
        {!run && !comparison && !error ? <p className="muted">Loading…</p> : null}
      </main>
    </div>
  )
}
