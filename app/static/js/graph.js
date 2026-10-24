// Score history (GRA-01…08) in the "Kursblatt" style (docs/design.md, section 4).
// Data from graph.json, colors, fonts and sizes from tokens.css, texts from the data
// attributes of #graph. No fixed values here either.
(function () {
  "use strict";

  const container = document.getElementById("graph");
  if (!container) return;
  const status = document.getElementById("graph-status");
  const links = document.querySelectorAll(".tab[data-range]");
  const rows = document.querySelectorAll(".rank[data-user]");
  const texts = JSON.parse(container.dataset.texts);

  function showStatus(text) {
    status.textContent = text || "";
    status.hidden = !text;
  }

  if (!window.echarts) {
    // CDN unreachable, blocked, or the SRI check failed.
    container.hidden = true;
    showStatus(texts.loadFailed);
    return;
  }

  const style = getComputedStyle(document.documentElement);
  const token = (name) => style.getPropertyValue(name).trim();
  const number = (name) => parseFloat(token(name));
  const theme = {
    ink: token("--color-ink"),
    faint: token("--color-faint"),
    line: token("--color-line"),
    series: token("--color-series"),
    up: token("--color-up"),
    down: token("--color-down"),
    bg: token("--color-bg"),
    mono: token("--font-mono"),
    semibold: token("--weight-semibold"),
    fontSize: number("--graph-font-size"),
    lineWidth: number("--graph-line-width"),
    lineRole: number("--graph-line-width-role"),
    lineMe: number("--graph-line-width-me"),
    endDot: number("--graph-end-dot"),
    endDotBorder: number("--graph-end-dot-border"),
    blur: number("--graph-blur-opacity"),
    markerHeight: number("--graph-marker-height"),
  };
  const ROLE_COLORS = { leader: theme.ink, gain: theme.up, drop: theme.down };
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const duration = reducedMotion ? 0 : number("--graph-animation-ms");

  const chart = echarts.init(container, null, { renderer: "canvas" });
  new ResizeObserver(() => chart.resize()).observe(container);

  let names = {};
  let request = 0;
  let focused = null;

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
  }

  // Scores arrive rounded for display (A13); only the decimal point is swapped.
  function formatScore(value) {
    return value.toFixed(1).replace(".", texts.decimalSeparator);
  }

  function isoWeek(ms) {
    const local = new Date(ms);
    const date = new Date(Date.UTC(local.getFullYear(), local.getMonth(), local.getDate()));
    date.setUTCDate(date.getUTCDate() + 4 - (date.getUTCDay() || 7)); // the week's Thursday
    const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
    return Math.ceil(((date - yearStart) / 86400000 + 1) / 7);
  }

  function axisLabel(cadence) {
    if (cadence === "weekly") {
      // Ticks may fall twice into one week: label each week once.
      let previous = null;
      return (value, index) => {
        const week = isoWeek(value);
        if (index === 0) previous = null;
        if (week === previous) return "";
        previous = week;
        return texts.week + week;
      };
    }
    return { year: "{yyyy}", month: "{dd}.{MM}.", day: "{dd}.{MM}.", hour: "{dd}.{MM}." };
  }

  // GRA-06: the y axis zooms on the data, in whole numbers within 0–10, always with 5.
  function yRange(data) {
    const values = data.series.flatMap((s) => s.points.filter(Boolean).map((p) => p[0]));
    const low = Math.min(4.5, ...values);
    const high = Math.max(5.5, ...values);
    return { min: Math.max(0, Math.floor(low - 0.3)), max: Math.min(10, Math.ceil(high + 0.3)) };
  }

  function tooltip(params) {
    if (params.seriesId === "markers") {
      return `${escapeHtml(params.data.date)}<br>${escapeHtml(params.data.text)}`;
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

  function lastIndex(points) {
    for (let i = points.length - 1; i >= 0; i -= 1) if (points[i]) return i;
    return -1;
  }

  function memberSeries(data) {
    return data.series.map((member) => {
      const color = ROLE_COLORS[member.role] || (member.me ? theme.ink : theme.series);
      const strong = Boolean(member.role) || member.me;
      const end = lastIndex(member.points);
      const label = names[member.id];
      return {
        id: String(member.id),
        type: "line",
        symbol: "circle",
        symbolSize: theme.endDot,
        connectNulls: false, // a gap where someone was not a member (MEM-03)
        triggerLineEvent: true,
        z: member.me ? 4 : strong ? 3 : 2,
        color,
        lineStyle: { width: member.me ? theme.lineMe : strong ? theme.lineRole : theme.lineWidth },
        // Points stay invisible but catch the tap for the tooltip; only "you" get an end dot.
        itemStyle: { opacity: 0 },
        emphasis: { focus: "series" },
        blur: { lineStyle: { opacity: theme.blur }, endLabel: { opacity: theme.blur } },
        // GRA-05: the name next to each line instead of a legend.
        endLabel: {
          show: end >= 0,
          formatter: () => `${label.toUpperCase()} ${formatScore(member.points[end][0])}`,
          color: strong ? theme.ink : theme.faint,
          fontFamily: theme.mono,
          fontSize: theme.fontSize,
          fontWeight: theme.semibold,
          distance: theme.fontSize / 2,
        },
        labelLayout: { moveOverlap: "shiftY" },
        data: member.points.map((point, i) => {
          const period = data.periods[i];
          if (!point) return { value: [period.t, "-"] };
          const item = {
            value: [period.t, point[0]],
            text: formatScore(point[0]),
            ups: point[1],
            downs: point[2],
            date: period.date,
          };
          if (member.me && i === end) {
            item.itemStyle = {
              opacity: 1,
              color,
              borderColor: theme.ink,
              borderWidth: theme.endDotBorder,
            };
          }
          return item;
        }),
      };
    });
  }

  // The starting value as a dashed line with its label (GRA-06).
  function startSeries(range) {
    return {
      id: "start",
      type: "line",
      data: [],
      silent: true,
      markLine: {
        silent: true,
        symbol: ["none", "none"],
        animation: false,
        lineStyle: { color: theme.ink, type: [3, 3], width: 1 },
        label: {
          position: "insideStartTop",
          formatter: texts.start,
          color: theme.faint,
          fontFamily: theme.mono,
          fontSize: theme.fontSize,
        },
        data: range.min < 5 && range.max > 5 ? [{ yAxis: 5 }] : [],
      },
    };
  }

  // GRA-07: joins, departures, settings and anonymity as small ink ticks on the x axis.
  function markerSeries(data, range) {
    return {
      id: "markers",
      type: "scatter",
      symbol: "rect",
      symbolSize: [1, theme.markerHeight],
      symbolOffset: [0, -theme.markerHeight / 2],
      color: theme.ink,
      z: 5,
      data: data.markers.map((marker) => ({
        value: [marker.t, range.min],
        date: marker.date,
        text: marker.text,
      })),
    };
  }

  function option(data) {
    const range = yRange(data);
    const axisText = { color: theme.faint, fontFamily: theme.mono, fontSize: theme.fontSize };
    return {
      backgroundColor: "transparent",
      animation: !reducedMotion,
      animationDuration: duration,
      animationDurationUpdate: duration,
      textStyle: { fontFamily: theme.mono, color: theme.ink },
      // Room on the right for the names at the line ends.
      grid: { left: 0, right: theme.fontSize * 9, top: theme.fontSize, bottom: 0, containLabel: true },
      tooltip: {
        trigger: "item",
        confine: true,
        backgroundColor: theme.bg,
        borderColor: theme.ink,
        borderWidth: 1,
        borderRadius: 0,
        extraCssText: "box-shadow: none",
        textStyle: { color: theme.ink, fontFamily: theme.mono, fontSize: theme.fontSize + 2 },
        formatter: tooltip,
      },
      xAxis: {
        type: "time",
        // One label per week at most for weekly groups (KW numbers).
        minInterval: data.cadence === "weekly" ? 7 * 86400000 : 86400000,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { ...axisText, hideOverlap: true, formatter: axisLabel(data.cadence) },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        min: range.min,
        max: range.max,
        interval: 1,
        // 5 carries the "Startwert 5,0" label of the dashed line instead.
        axisLabel: { ...axisText, formatter: (value) => (value === 5 ? "" : String(value)) },
        splitLine: { lineStyle: { color: theme.line } },
      },
      // GRA-08: pinch and drag on the phone, wheel and drag on the desktop.
      dataZoom: [{ type: "inside", filterMode: "none" }],
      series: [...memberSeries(data), startSeries(range), markerSeries(data, range)],
    };
  }

  function render(data) {
    names = {};
    for (const member of data.series) {
      names[member.id] = member.former
        ? texts.former.replace("{name}", () => member.name)
        : member.name;
    }
    const empty = data.series.length === 0;
    container.hidden = empty;
    showStatus(empty ? texts.empty : "");
    focused = null;
    chart.setOption(option(data), { notMerge: true });
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
      links.forEach((other) => other.removeAttribute("aria-current"));
      link.setAttribute("aria-current", "true");
      history.replaceState(null, "", link.href);
      load(link.dataset.range);
    });
  });

  // GRA-05: tapping a leaderboard row highlights that person's line; again to undo.
  rows.forEach((row) => {
    row.addEventListener("click", () => {
      const id = row.dataset.user;
      chart.dispatchAction({ type: "downplay" });
      focused = focused === id ? null : id;
      if (focused) chart.dispatchAction({ type: "highlight", seriesId: focused });
    });
  });

  load(container.dataset.range);
})();
