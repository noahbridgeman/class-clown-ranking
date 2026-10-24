// Score history (GRA-01…08). Data comes from graph.json, colors, fonts and sizes from
// tokens.css, texts from the data attributes of #graph. No fixed values here either.
(function () {
  "use strict";

  const container = document.getElementById("graph");
  if (!container) return;
  const status = document.getElementById("graph-status");
  const links = document.querySelectorAll(".graph-range");
  const texts = JSON.parse(container.dataset.texts);
  if (!window.echarts) {
    // CDN unreachable, blocked, or the SRI check failed.
    container.hidden = true;
    status.textContent = texts.loadFailed;
    status.hidden = false;
    return;
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name) => style.getPropertyValue(name).trim();
  const number = (name) => parseFloat(token(name));
  const theme = {
    text: token("--color-text"),
    muted: token("--color-muted"),
    border: token("--color-border"),
    surface: token("--color-surface"),
    accent: token("--color-accent"),
    font: token("--font-sans"),
    fontSize: number("--graph-font-size"),
    legendSpace: number("--graph-legend-space"),
    line: number("--graph-line-width"),
    lineMe: number("--graph-line-width-me"),
    lineEmphasis: number("--graph-line-width-emphasis"),
    glow: number("--graph-glow"),
    markerWidth: number("--graph-marker-width"),
    symbol: number("--graph-symbol-size"),
    blur: number("--graph-blur-opacity"),
    duration: number("--graph-animation-ms"),
  };

  const chart = echarts.init(container, null, { renderer: "canvas" });
  new ResizeObserver(() => chart.resize()).observe(container);
  chart.setOption(baseOption());

  let names = {};
  let request = 0;

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
  }

  function showStatus(text) {
    status.textContent = text || "";
    status.hidden = !text;
  }

  function baseOption() {
    const axisText = { color: theme.muted, fontFamily: theme.font, fontSize: theme.fontSize };
    return {
      backgroundColor: "transparent",
      textStyle: { fontFamily: theme.font, color: theme.text },
      animationDuration: theme.duration,
      animationDurationUpdate: theme.duration,
      animationEasing: "cubicOut",
      grid: { left: 0, right: theme.fontSize, top: theme.legendSpace, bottom: 0, containLabel: true },
      legend: {
        type: "scroll",
        top: 0,
        textStyle: axisText,
        pageTextStyle: axisText,
        pageIconColor: theme.text,
        pageIconInactiveColor: theme.border,
        inactiveColor: theme.border,
        icon: "circle",
        formatter: (id) => names[id] || id,
      },
      tooltip: {
        trigger: "item",
        confine: true,
        backgroundColor: theme.surface,
        borderColor: theme.border,
        textStyle: { color: theme.text, fontFamily: theme.font },
        formatter: tooltip,
      },
      xAxis: {
        type: "time",
        axisLine: { lineStyle: { color: theme.border } },
        axisLabel: {
          ...axisText,
          hideOverlap: true,
          formatter: { year: "{yyyy}", month: "{dd}.{MM}.", day: "{dd}.{MM}.", hour: "{dd}.{MM}." },
        },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        min: 0,
        max: 10,
        interval: 2,
        axisLabel: axisText,
        splitLine: { lineStyle: { color: theme.border } },
      },
      // GRA-08: pinch and drag on the phone, wheel and drag on the desktop.
      dataZoom: [{ type: "inside", filterMode: "none" }],
    };
  }

  function tooltip(params) {
    if (params.componentType === "markLine") {
      return `${escapeHtml(params.data.date)}<br>${escapeHtml(params.name)}`;
    }
    const point = params.data;
    if (!point || point.text === undefined) return "";
    return (
      `<strong>${escapeHtml(names[params.seriesId] || "")}</strong><br>` +
      `${escapeHtml(point.date)}<br>` +
      `${escapeHtml(texts.score)}: ${escapeHtml(point.text)}<br>` +
      `${escapeHtml(texts.ups)}: ${point.ups} · ${escapeHtml(texts.downs)}: ${point.downs}`
    );
  }

  function memberSeries(data) {
    return data.series.map((member) => ({
      id: String(member.id),
      name: String(member.id), // display names may repeat, ids do not
      type: "line",
      smooth: 0.35,
      symbol: "circle",
      symbolSize: theme.symbol,
      showAllSymbol: "auto",
      connectNulls: false, // a gap where someone was not a member (MEM-03)
      triggerLineEvent: true,
      z: member.me ? 3 : 2,
      color: member.color,
      lineStyle: {
        width: member.me ? theme.lineMe : theme.line,
        shadowBlur: theme.glow,
        shadowColor: member.color,
      },
      emphasis: { focus: "series", lineStyle: { width: theme.lineEmphasis } },
      blur: { lineStyle: { opacity: theme.blur }, itemStyle: { opacity: theme.blur } },
      data: member.points.map((point, i) => {
        const period = data.periods[i];
        if (!point) return { value: [period.t, "-"] };
        return {
          value: [period.t, point[0]],
          text: point[0].toFixed(1).replace(".", texts.decimalSeparator),
          ups: point[1],
          downs: point[2],
          date: period.date,
        };
      }),
    }));
  }

  function markerSeries(data) {
    return {
      id: "markers",
      type: "line",
      data: [],
      markLine: {
        symbol: ["none", "none"],
        label: { show: false },
        emphasis: { label: { show: false }, lineStyle: { width: theme.line } },
        data: data.markers.map((marker) => ({
          xAxis: marker.t,
          name: marker.text,
          date: marker.date,
          lineStyle: {
            color: marker.color || theme.accent,
            type: "dashed",
            width: theme.markerWidth,
            opacity: 1,
          },
        })),
      },
    };
  }

  function render(data) {
    names = {};
    for (const member of data.series) {
      names[member.id] = member.former ? texts.former.replace("{name}", () => member.name) : member.name;
    }
    const empty = data.series.length === 0;
    container.hidden = empty;
    showStatus(empty ? texts.empty : "");
    chart.setOption(
      {
        legend: { data: data.series.map((member) => String(member.id)) },
        series: [...memberSeries(data), markerSeries(data)],
        dataZoom: [{ start: 0, end: 100 }],
      },
      { replaceMerge: ["series"] },
    );
  }

  async function load(range) {
    const id = ++request;
    const url = `${container.dataset.url}?range=${encodeURIComponent(range)}`;
    try {
      const response = await fetch(url, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(response.statusText);
      const data = await response.json();
      if (id === request) render(data); // ignore answers overtaken by a newer click
    } catch (error) {
      if (id === request) showStatus(texts.loadFailed);
    }
  }

  links.forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      const range = link.dataset.range;
      links.forEach((other) => other.removeAttribute("aria-current"));
      link.setAttribute("aria-current", "true");
      history.replaceState(null, "", link.href);
      load(range);
    });
  });

  load(container.dataset.range);
})();
