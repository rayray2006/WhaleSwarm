<template>
  <div class="graph-panel" ref="container">
    <svg ref="svg"></svg>
    <div v-if="hoveredNode" class="tooltip" :style="tooltipStyle">
      <div class="tooltip-type tag">{{ hoveredNode.type }}</div>
      <div class="tooltip-name">{{ hoveredNode.name }}</div>
      <div class="tooltip-summary">{{ hoveredNode.summary }}</div>
    </div>
  </div>
</template>

<script>
import * as d3 from 'd3'

const TYPE_COLORS = {
  Journalist: '#FF6B1A',
  Politician: '#E53E3E',
  CEO: '#43C165',
  Company: '#3182CE',
  Organization: '#805AD5',
  Professor: '#D69E2E',
  Student: '#38B2AC',
  MediaOutlet: '#ED64A6',
  Person: '#718096',
  Entity: '#666666',
}

function getColor(type) {
  return TYPE_COLORS[type] || TYPE_COLORS.Entity
}

export default {
  name: 'GraphPanel',
  props: {
    graphData: { type: Object, default: () => ({ nodes: [], edges: [] }) },
  },
  data() {
    return {
      hoveredNode: null,
      tooltipStyle: {},
      simulation: null,
    }
  },
  watch: {
    graphData: {
      handler() { this.renderGraph() },
      deep: true,
    },
  },
  mounted() {
    this.renderGraph()
    window.addEventListener('resize', this.renderGraph)
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.renderGraph)
    if (this.simulation) this.simulation.stop()
  },
  methods: {
    renderGraph() {
      if (!this.graphData.nodes?.length) return

      const container = this.$refs.container
      const svg = d3.select(this.$refs.svg)
      svg.selectAll('*').remove()

      const width = container.clientWidth
      const height = container.clientHeight

      svg.attr('width', width).attr('height', height)

      const g = svg.append('g')

      // Zoom
      const zoom = d3.zoom()
        .scaleExtent([0.1, 4])
        .on('zoom', (event) => g.attr('transform', event.transform))
      svg.call(zoom)

      const nodes = this.graphData.nodes.map(d => ({ ...d }))
      const edges = this.graphData.edges
        .map(d => ({
          ...d,
          source: d.source,
          target: d.target,
        }))
        .filter(d => {
          const hasSource = nodes.some(n => n.id === d.source)
          const hasTarget = nodes.some(n => n.id === d.target)
          return hasSource && hasTarget
        })

      // Force simulation
      if (this.simulation) this.simulation.stop()

      this.simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(edges).id(d => d.id).distance(100))
        .force('charge', d3.forceManyBody().strength(-300))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(25))

      // Edges
      const link = g.append('g')
        .selectAll('line')
        .data(edges)
        .join('line')
        .attr('stroke', '#333')
        .attr('stroke-width', 1)
        .attr('stroke-opacity', 0.6)

      // Nodes
      const node = g.append('g')
        .selectAll('circle')
        .data(nodes)
        .join('circle')
        .attr('r', d => 6 + Math.min(d.degree || 0, 10))
        .attr('fill', d => getColor(d.type))
        .attr('stroke', '#0A0A0A')
        .attr('stroke-width', 1.5)
        .style('cursor', 'pointer')
        .on('mouseover', (event, d) => {
          this.hoveredNode = d
          this.tooltipStyle = {
            left: event.offsetX + 15 + 'px',
            top: event.offsetY - 10 + 'px',
          }
        })
        .on('mouseout', () => { this.hoveredNode = null })
        .call(d3.drag()
          .on('start', (event, d) => {
            if (!event.active) this.simulation.alphaTarget(0.3).restart()
            d.fx = d.x; d.fy = d.y
          })
          .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
          .on('end', (event, d) => {
            if (!event.active) this.simulation.alphaTarget(0)
            d.fx = null; d.fy = null
          })
        )

      // Labels
      const label = g.append('g')
        .selectAll('text')
        .data(nodes)
        .join('text')
        .text(d => d.name)
        .attr('font-size', 10)
        .attr('font-family', 'Space Mono, monospace')
        .attr('fill', '#BBBBBB')
        .attr('dx', 12)
        .attr('dy', 4)

      this.simulation.on('tick', () => {
        link
          .attr('x1', d => d.source.x)
          .attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x)
          .attr('y2', d => d.target.y)
        node.attr('cx', d => d.x).attr('cy', d => d.y)
        label.attr('x', d => d.x).attr('y', d => d.y)
      })
    },
  },
}
</script>

<style scoped>
.graph-panel {
  width: 100%;
  height: 100%;
  position: relative;
  background: var(--background);
  overflow: hidden;
}

svg {
  width: 100%;
  height: 100%;
}

.tooltip {
  position: absolute;
  background: var(--surface-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--space-2);
  max-width: 250px;
  pointer-events: none;
  z-index: 100;
}

.tooltip-type {
  margin-bottom: 4px;
}

.tooltip-name {
  font-weight: 700;
  font-size: 13px;
  margin-bottom: 4px;
}

.tooltip-summary {
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.4;
}
</style>
