// SET-05: mini graph of the example history on the settings page. The numbers come from
// data-preview, rendered by the server; HTMX replaces the block when K, d or the cadence
// change, so the chart is drawn again after every swap.
(function () {
  "use strict";

  if (!window.echarts) return; // the text below the chart says the same without it

  const style = getComputedStyle(document.documentElement);
  const token = (name) => style.getPropertyValue(name).trim();
  const number = (name) => parseFloat(token(name));

  function draw() {
    const container = document.getElementById("preview-chart");
    if (!container || container.dataset.drawn) return;
    container.dataset.drawn = "true";
    const data = JSON.parse(container.dataset.preview);
    const texts = JSON.parse(container.dataset.texts);
    const axisText = { color: token("--color-muted"), fontSize: number("--graph-font-size") };
    const accent = token("--color-ink");
    const chart = echarts.init(container, null, { renderer: "canvas" });
    new ResizeObserver(() => chart.resize()).observe(container);
    chart.setOption({
      backgroundColor: "transparent",
      animationDuration: number("--graph-animation-ms"),
      textStyle: { fontFamily: token("--font-mono") },
      grid: { left: 0, right: axisText.fontSize, top: axisText.fontSize, bottom: 0, containLabel: true },
      tooltip: { show: false },
      xAxis: {
        type: "value",
        min: 0,
        max: data.weeks[data.weeks.length - 1],
        interval: 6,
        name: texts.weeks,
        nameLocation: "middle",
        nameGap: axisText.fontSize * 1.8,
        nameTextStyle: axisText,
        axisLabel: axisText,
        axisLine: { lineStyle: { color: token("--color-line") } },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 10,
        interval: 5,
        axisLabel: axisText,
        splitLine: { lineStyle: { color: token("--color-line") } },
      },
      series: [
        {
          type: "line",
          smooth: true,
          showSymbol: false,
          data: data.weeks.map((week, i) => [week, data.scores[i]]),
          lineStyle: {
            color: accent,
            width: number("--graph-line-width"),
            shadowBlur: 0,
            shadowColor: accent,
          },
        },
      ],
    });
  }

  draw();
  document.body.addEventListener("htmx:afterSwap", draw);
})();
