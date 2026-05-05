# D3.js Force-Directed Graph Integration

Embedding D3 force graphs into an existing HTML dashboard page.

## Setup

1. Add D3 library in `<head>`: `<script src="https://d3js.org/d3.v7.min.js"></script>`
2. Add CSS for graph container, nodes, links, tooltip in `<style>` block
3. Add container div: `<div id="topic-graph-container"></div>` with fixed height (e.g., 500px)
4. Add JS functions after existing app code, before `loadData()` or `render()` call

## Force Configuration Order

**CRITICAL**: Define scale functions BEFORE using them in force configs.

```js
// ✅ CORRECT — radiusScale defined first
const radiusScale = d3.scaleSqrt().domain([1, max]).range([5, 28]);
const simulation = d3.forceSimulation(nodes)
  .force('collision', d3.forceCollide().radius(d => radiusScale(d.count) + 4));

// ❌ WRONG — const in temporal dead zone
const simulation = d3.forceSimulation(nodes)
  .force('collision', d3.forceCollide().radius(d => radiusScale(d.count) + 4));
const radiusScale = d3.scaleSqrt().domain([1, max]).range([5, 28]);
```

## Data Access

When embedding in an existing app, use the app's global data variable name exactly:

```js
// If app uses DATA.videos:
(DATA ? DATA.videos : []).forEach(v => { ... });

// Don't invent new names like videoData
```

## Hooking into App Lifecycle

Add graph init to the existing `render()` function rather than wrapping `loadData()`:

```js
function render() {
  renderStats();
  renderTopicBars();
  // ... existing calls ...
  renderVideos();
  // Add graph init here:
  buildGraphChannelFilter();
  initTopicGraph();
}
```

## Zoom + Pan

```js
const g = svg.append('g');
svg.call(d3.zoom().scaleExtent([0.2, 5]).on('zoom', e => g.attr('transform', e.transform)));
```

## Node Highlighting Pattern

Click-to-highlight connected nodes:

```js
.on('click', (e, d) => {
  if (activeNode === d.id) {
    // Deselect — remove all classes
    activeNode = null;
    node.classed('dimmed', false).classed('highlighted', false);
    link.classed('dimmed', false).classed('highlighted', false);
    return;
  }
  activeNode = d.id;
  const connected = new Set([d.id]);
  link.each(function(l) {
    if (l.source.id === d.id || l.target.id === d.id) {
      connected.add(l.source.id); connected.add(l.target.id);
    }
  });
  node.classed('dimmed', n => !connected.has(n.id))
      .classed('highlighted', n => n.id === d.id);
  link.classed('dimmed', l => l.source.id !== d.id && l.target.id !== d.id)
      .classed('highlighted', l => l.source.id === d.id || l.target.id === d.id);
});
```

## CSS Classes for Graph States

```css
.node circle { cursor: pointer; stroke-width: 1.5; }
.node text { fill: #8b949e; font-size: 10px; pointer-events: none; }
.node:hover circle { stroke: #fff; stroke-width: 2.5; }
.node.dimmed circle { opacity: 0.15; }
.node.dimmed text { opacity: 0.1; }
.link.dimmed { stroke-opacity: 0.05; }
.node.highlighted circle { stroke: #fff; stroke-width: 2.5; }
.link.highlighted { stroke: #58a6ff; stroke-opacity: 0.6; stroke-width: 2; }
```

## Edge Building from Co-occurrence

```js
const edgeMap = {};
videos.forEach(v => {
  const topics = v.specific_topics.filter(t => validTopics.includes(t));
  for (let i = 0; i < topics.length; i++) {
    for (let j = i + 1; j < topics.length; j++) {
      const key = [topics[i], topics[j]].sort().join('|||');
      if (!edgeMap[key]) edgeMap[key] = { source: topics[i], target: topics[j], weight: 0 };
      edgeMap[key].weight++;
    }
  }
});
const links = Object.values(edgeMap);
```

## Responsive Resize

```js
window.addEventListener('resize', () => {
  svg.attr('width', container.clientWidth).attr('height', 500);
  simulation.force('center', d3.forceCenter(container.clientWidth / 2, 250));
  simulation.alpha(0.3).restart();
});
```
