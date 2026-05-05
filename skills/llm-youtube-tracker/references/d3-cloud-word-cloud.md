# d3-cloud Word Cloud Integration

Replace bar charts with word clouds for topic distribution visualization.

## CDN

```html
<script src="https://cdn.jsdelivr.net/npm/d3-cloud@1.2.7/build/d3.layout.cloud.min.js"></script>
```

## Pattern

```js
function renderTopicCloud(entries, containerEl) {
  const maxCount = entries[0][1];
  const minCount = entries[entries.length - 1][1];
  const fontScale = d3.scaleSqrt().domain([minCount, maxCount]).range([12, 42]);
  const colorScale = d3.scaleOrdinal(d3.schemeTableau10);
  const width = containerEl.clientWidth || 400;
  const height = 260;

  const words = entries.map(([text, count]) => ({
    text: text.length > 30 ? text.slice(0, 27) + '…' : text,
    fullText: text,
    size: fontScale(count),
    count
  }));

  d3.layout.cloud()
    .size([width, height])
    .words(words)
    .padding(3)
    .rotate(() => (Math.random() > 0.7 ? 90 : 0))  // 30% rotated
    .fontSize(d => d.size)
    .spiral('archimedean')
    .on('end', draw)
    .start();

  function draw(words) {
    d3.select(containerEl).select('svg').remove();
    const svg = d3.select(containerEl).append('svg')
      .attr('width', width).attr('height', height);
    svg.append('g')
      .attr('transform', `translate(${width/2},${height/2})`)
      .selectAll('text').data(words).join('text')
      .style('font-size', d => d.size + 'px')
      .style('font-weight', d => d.size > 28 ? '700' : '500')
      .style('fill', (d, i) => colorScale(i))
      .style('opacity', d => 0.6 + (d.size / 42) * 0.4)
      .attr('text-anchor', 'middle')
      .attr('transform', d => `translate(${d.x},${d.y}) rotate(${d.rotate})`)
      .text(d => d.text)
      .append('title')
      .text(d => `${d.fullText} (${d.count} videos)`);
  }
}
```

## Key Tips

- **Limit to top 50-60 entries** — more becomes unreadable
- **Use `d3.scaleSqrt`** for font sizing — linear makes small topics invisible
- **Truncate long names** (>30 chars) with `…`
- **Layout is async** — `draw` fires after computation completes, not synchronously
- **Container needs explicit height** (e.g., 260px) — SVG won't auto-size
- **Rotate ~30% of words** 90° for visual variety
- **Opacity gradient**: larger words = more opaque, creates depth
- **`d3.schemeTableau10`** gives 10 distinct, accessible colors
