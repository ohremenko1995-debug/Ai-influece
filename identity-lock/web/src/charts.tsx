/**
 * SVG charts for the dashboard.
 *
 * Deliberately the same visual language as the static HTML report: same axes, same
 * threshold styling, same accept/reject colours. Two views of one run should not
 * look like two different tools.
 */

import type { JSX } from 'react'

interface Box {
  width: number
  height: number
  left: number
  right: number
  top: number
  bottom: number
}

const BOX: Box = { width: 640, height: 240, left: 46, right: 14, top: 12, bottom: 36 }

function niceTicks(low: number, high: number, count = 5): number[] {
  if (high <= low) return [low]
  const raw = (high - low) / Math.max(count - 1, 1)
  const magnitude = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1)))
  const step = [1, 2, 2.5, 5, 10].map((s) => s * magnitude).find((s) => s >= raw) ?? magnitude
  const ticks: number[] = []
  for (let value = Math.ceil(low / step) * step; value <= high + step * 1e-9; value += step) {
    ticks.push(Number(value.toFixed(10)))
  }
  return ticks.length > 0 ? ticks : [low, high]
}

const fmt = (value: number): string => {
  if (Math.abs(value) >= 100) return value.toFixed(0)
  const text = (Math.abs(value) >= 1 ? value.toFixed(2) : value.toFixed(3)).replace(/\.?0+$/, '')
  return text === '' || text === '-' ? '0' : text
}

function makeScales(box: Box, xRange: [number, number], yRange: [number, number]) {
  const [x0, x1] = xRange[1] > xRange[0] ? xRange : [xRange[0], xRange[0] + 1]
  const [y0, y1] = yRange[1] > yRange[0] ? yRange : [yRange[0], yRange[0] + 1]
  const innerWidth = box.width - box.left - box.right
  const innerHeight = box.height - box.top - box.bottom
  return {
    x0,
    x1,
    y0,
    y1,
    sx: (value: number) => box.left + ((value - x0) / (x1 - x0)) * innerWidth,
    sy: (value: number) => box.top + innerHeight - ((value - y0) / (y1 - y0)) * innerHeight,
  }
}

interface FrameProps {
  box: Box
  scales: ReturnType<typeof makeScales>
  xLabel: string
  yLabel: string
  hideXTicks?: boolean
}

function Frame({ box, scales, xLabel, yLabel, hideXTicks }: FrameProps): JSX.Element {
  const yTicks = niceTicks(scales.y0, scales.y1).filter((t) => t >= scales.y0 && t <= scales.y1)
  const xTicks = hideXTicks
    ? []
    : niceTicks(scales.x0, scales.x1).filter((t) => t >= scales.x0 && t <= scales.x1)
  return (
    <g>
      {yTicks.map((tick) => (
        <g key={`y${tick}`}>
          <line className="grid" x1={box.left} y1={scales.sy(tick)} x2={box.width - box.right} y2={scales.sy(tick)} />
          <text className="tick" x={box.left - 6} y={scales.sy(tick) + 3.5} textAnchor="end">
            {fmt(tick)}
          </text>
        </g>
      ))}
      {xTicks.map((tick) => (
        <text key={`x${tick}`} className="tick" x={scales.sx(tick)} y={box.height - 14} textAnchor="middle">
          {fmt(tick)}
        </text>
      ))}
      <text className="axis" x={box.width / 2} y={box.height - 2} textAnchor="middle">
        {xLabel}
      </text>
      <text className="axis" transform={`translate(11,${box.height / 2}) rotate(-90)`} textAnchor="middle">
        {yLabel}
      </text>
    </g>
  )
}

export function DriftChart({
  values,
  accepted,
  threshold,
  slopePer10,
}: {
  values: number[]
  accepted: boolean[]
  threshold: number
  slopePer10: number
}): JSX.Element | null {
  if (values.length === 0) return null
  const low = Math.min(...values, threshold) - 0.05
  const high = Math.max(...values, threshold) + 0.05
  const scales = makeScales(BOX, [0, values.length - 1], [low, high])
  const mean = values.reduce((a, b) => a + b, 0) / values.length
  const centre = (values.length - 1) / 2
  const slope = slopePer10 / 10
  const label = `accept ≥ ${fmt(threshold)}`

  return (
    <svg className="chart" viewBox={`0 0 ${BOX.width} ${BOX.height}`} role="img" aria-label="identity across the batch">
      <Frame box={BOX} scales={scales} xLabel="position in batch" yLabel="identity" />
      <line
        className="threshold"
        x1={BOX.left}
        y1={scales.sy(threshold)}
        x2={BOX.width - BOX.right - label.length * 7 - 6}
        y2={scales.sy(threshold)}
      />
      <text className="tick threshold-label" x={BOX.width - BOX.right} y={scales.sy(threshold) + 3.5} textAnchor="end">
        {label}
      </text>
      <line
        className="trend"
        x1={scales.sx(0)}
        y1={scales.sy(mean + slope * (0 - centre))}
        x2={scales.sx(values.length - 1)}
        y2={scales.sy(mean + slope * (values.length - 1 - centre))}
      />
      {values.map((value, index) => (
        <circle
          key={index}
          className={accepted[index] ? 'dot ok' : 'dot bad'}
          cx={scales.sx(index)}
          cy={scales.sy(value)}
          r={3.8}
        />
      ))}
    </svg>
  )
}

export function Scatter({
  xs,
  ys,
  accepted,
  xThreshold,
  yThreshold,
  xLabel,
  yLabel,
}: {
  xs: number[]
  ys: number[]
  accepted: boolean[]
  xThreshold?: number | undefined
  yThreshold?: number | undefined
  xLabel: string
  yLabel: string
}): JSX.Element | null {
  if (xs.length === 0) return null
  const box = { ...BOX, width: 320, height: 240, left: 40 }
  const xValues = xThreshold === undefined ? xs : [...xs, xThreshold]
  const yValues = yThreshold === undefined ? ys : [...ys, yThreshold]
  const scales = makeScales(
    box,
    [Math.min(...xValues) - 0.03, Math.max(...xValues) + 0.03],
    [Math.min(...yValues) - 0.03, Math.max(...yValues) + 0.03],
  )
  return (
    <svg className="chart" viewBox={`0 0 ${box.width} ${box.height}`} role="img" aria-label={`${yLabel} against ${xLabel}`}>
      <Frame box={box} scales={scales} xLabel={xLabel} yLabel={yLabel} />
      {xThreshold !== undefined && yThreshold !== undefined && (
        <rect
          className="region"
          x={scales.sx(xThreshold)}
          y={box.top}
          width={Math.max(box.width - box.right - scales.sx(xThreshold), 0)}
          height={Math.max(scales.sy(yThreshold) - box.top, 0)}
        />
      )}
      {xThreshold !== undefined && (
        <line className="threshold" x1={scales.sx(xThreshold)} y1={box.top} x2={scales.sx(xThreshold)} y2={scales.sy(scales.y0)} />
      )}
      {yThreshold !== undefined && (
        <line className="threshold" x1={box.left} y1={scales.sy(yThreshold)} x2={box.width - box.right} y2={scales.sy(yThreshold)} />
      )}
      {xs.map((value, index) => (
        <circle
          key={index}
          className={accepted[index] ? 'dot ok' : 'dot bad'}
          cx={scales.sx(value)}
          cy={scales.sy(ys[index] ?? 0)}
          r={3.8}
        />
      ))}
    </svg>
  )
}

export function DeltaBars({
  deltas,
  labels,
  ci,
}: {
  deltas: number[]
  labels: string[]
  ci: [number, number]
}): JSX.Element | null {
  if (deltas.length === 0) return null
  const box = { ...BOX, height: 260, bottom: 46 }
  const order = deltas.map((_, index) => index).sort((a, b) => (deltas[a] ?? 0) - (deltas[b] ?? 0))
  const limit = Math.max(...deltas.map(Math.abs), 1e-6) * 1.15
  const scales = makeScales(box, [-0.5, deltas.length - 0.5], [-limit, limit])
  const slot = (box.width - box.left - box.right) / deltas.length
  const zero = scales.sy(0)
  return (
    <svg className="chart" viewBox={`0 0 ${box.width} ${box.height}`} role="img" aria-label="paired differences">
      <Frame box={box} scales={scales} xLabel="paired cell (sorted by delta)" yLabel="challenger − baseline" hideXTicks />
      <rect
        className="ci"
        x={box.left}
        y={Math.min(scales.sy(ci[1]), scales.sy(ci[0]))}
        width={box.width - box.left - box.right}
        height={Math.abs(scales.sy(ci[0]) - scales.sy(ci[1]))}
      />
      <line className="zero" x1={box.left} y1={zero} x2={box.width - box.right} y2={zero} />
      {order.map((index, position) => {
        const value = deltas[index] ?? 0
        return (
          <rect
            key={index}
            className={value > 0 ? 'bar ok' : 'bar bad'}
            x={scales.sx(position) - slot * 0.35}
            y={scales.sy(Math.max(value, 0))}
            width={slot * 0.7}
            height={Math.abs(scales.sy(value) - zero)}
          >
            <title>{`${labels[index] ?? ''}: ${value >= 0 ? '+' : ''}${value.toFixed(4)}`}</title>
          </rect>
        )
      })}
    </svg>
  )
}
