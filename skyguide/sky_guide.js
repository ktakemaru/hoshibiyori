(function () {
  "use strict";
  // 数値JSON(sg-data)と解説JSON(sg-commentary)だけを読む。文章はtextContentで入れる(HTMLとして解釈しない)。
  var DATA = JSON.parse(document.getElementById("sg-data").textContent);
  var COMM = JSON.parse(document.getElementById("sg-commentary").textContent);
  var D = { times: DATA.times, frames: DATA.frames, starmag: DATA.starmag };
  var HZ = DATA.horizon_deg;
  var CARDS = COMM.cards;
  var NAMED = COMM.peaks || [];
  // 解説の山名は、数値側のピーク候補のうち最も近い方位のものに仰角を結びつける
  var PEAKS = NAMED.map(function (n) {
    var best = null;
    (DATA.peak_candidates || []).forEach(function (c) {
      var d = Math.abs(((c.az - n.az + 540) % 360) - 180);
      if (d <= 3 && (!best || d < best.d)) best = { d: d, alt: c.alt, az: c.az };
    });
    return best ? { az: best.az, alt: best.alt, name: n.name } : null;
  }).filter(Boolean);

  var el = function (id) { return document.getElementById(id); };
  var initial = Math.max(0, D.times.indexOf(COMM.initial_time));
  if (COMM.initial_time === undefined || D.times.indexOf(COMM.initial_time) < 0) initial = Math.floor(D.times.length / 2);
  var state = { ti: initial, facing: 270, fr: null, card: null, timer: null };
  var wrap = function (d) { return ((d + 180) % 360 + 360) % 360 - 180; };

  // --- cloud bars ---
  (function () {
    var bars = el("bars"), hrs = el("hours");
    if (!bars || !DATA.cloud) return;
    bars.style.setProperty("--n", DATA.cloud.hours.length);
    hrs.style.setProperty("--n", DATA.cloud.hours.length);
    DATA.cloud.hours.forEach(function (c) {
      var b = document.createElement("div"); b.className = "bar";
      var sp = document.createElement("span"); sp.textContent = String(c.pct);
      var i = document.createElement("i"); i.className = c.pct < 10 ? "ok" : ""; i.style.height = Math.max(2, c.pct * 0.7) + "px";
      b.appendChild(sp); b.appendChild(i); bars.appendChild(b);
      var s = document.createElement("span"); s.textContent = c.h + "時"; hrs.appendChild(s);
    });
  })();
  function cloudAt(hh) {
    if (!DATA.cloud) return null;
    var key = hh.slice(0, 2), v = null;
    DATA.cloud.hours.forEach(function (c) { if (c.h === key) v = c.pct; });
    return v;
  }

  // --- cards ---
  var cardsEl = el("cards");
  cardsEl.addEventListener("click", function (e) {
    var b = e.target.closest("button[data-card]"); if (!b) return;
    var c = CARDS.filter(function (x) { return x.id === b.getAttribute("data-card"); })[0];
    if (!c) return;
    var ti = D.times.indexOf(c.time); if (ti < 0) return;
    state.ti = ti; state.facing = c.az; state.fr = c.frame; state.card = c.id;
    el("slider").value = state.ti; stop(); draw();
    el("pano").scrollIntoView({ behavior: "smooth", block: "center" });
  });

  // --- controls ---
  el("slider").max = String(D.times.length - 1);
  el("slider").value = String(state.ti);
  el("slider").addEventListener("input", function (e) { state.ti = +e.target.value; state.card = null; stop(); draw(); });
  el("facing").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-az]"); if (!b) return;
    state.facing = +b.getAttribute("data-az"); state.fr = null; state.card = null; draw();
  });
  function stop() { if (state.timer) { clearInterval(state.timer); state.timer = null; } el("play").textContent = "再生"; }
  el("play").addEventListener("click", function () {
    if (state.timer) { stop(); return; }
    el("play").textContent = "停止";
    state.timer = setInterval(function () {
      state.ti = (state.ti + 1) % D.times.length; el("slider").value = state.ti; draw();
    }, 450);
  });

  // --- canvas helpers ---
  function setup(c, w, h) {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (c._w !== w || c._h !== h) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); c.style.height = h + "px"; c._w = w; c._h = h; }
    var x = c.getContext("2d"); x.setTransform(dpr, 0, 0, dpr, 0, 0); return x;
  }
  var LABEL = { "ベガ": 1, "デネブ": 1, "アルタイル": 1, "カペラ": 1, "アルデバラン": 1, "シリウス": 1, "フォーマルハウト": 1, "ポラリス(北極星)": 1, "すばる": 1, "アンドロメダ銀河": 1, "リゲル": 0, "アルニラム": 0, "ガンマ星": 0 };
  var LINES = [
    ["セギン", "ルクバー", "ガンマ星", "シェダル", "カフ"],
    ["ドゥーベ", "メラク", "フェクダ", "メグレズ", "ドゥーベ"], ["メグレズ", "アリオト", "ミザール", "アルカイド"],
    ["ベガ", "デネブ", "アルタイル", "ベガ"], ["アルニタク", "アルニラム", "ミンタカ"]
  ];
  var PCOL = { "土星": "#e8cf8a", "火星": "#e0795a", "木星": "#f2e6c8", "金星": "#fff3c4", "水星": "#cfcfcf" };
  var CLABEL = { "ポラリス(北極星)": "北極星", "アルニラム": "オリオン座 三つ星" };
  var FONT = "'Zen Kaku Gothic New', 'Hiragino Sans', 'Yu Gothic', sans-serif";
  var MONO = "'IBM Plex Mono', ui-monospace, Consolas, monospace";

  function starR(mag) { return Math.max(1.1, 3.4 - mag * 0.85); }

  function drawMW(x, f, proj, bw, W) {
    var p = f.plane, n = p.length, i, a, b, q1, q2;
    var passes = [[1.0, 0.05], [0.62, 0.07], [0.32, 0.09]];
    passes.forEach(function (ps) {
      x.lineCap = "round"; x.lineJoin = "round";
      for (i = 0; i < n; i++) {
        a = p[i]; b = p[(i + 1) % n];
        if (a[2] < -8 && b[2] < -8) continue;
        q1 = proj(a[1], a[2]); q2 = proj(b[1], b[2]);
        if (!q1 || !q2 || Math.abs(q1[0] - q2[0]) > W / 2) continue;
        x.strokeStyle = "rgba(190,208,255," + (ps[1] * (0.35 + a[3])) + ")";
        x.lineWidth = bw * ps[0] * (0.7 + 0.5 * a[3]);
        x.beginPath(); x.moveTo(q1[0], q1[1]); x.lineTo(q2[0], q2[1]); x.stroke();
      }
    });
  }

  // 月: 暗い円盤の上に輝面(輝面比illum)を描く。waxing=true(満ちていく)なら輝面は右側(空を見上げる向き)。flip=trueで左右反転(全天図は東が左)。
  function drawMoon(x, q, r, m, flip) {
    var k = m.illum, right = m.waxing !== flip;
    x.save(); x.translate(q[0], q[1]); if (!right) x.scale(-1, 1);
    x.fillStyle = "#2b3350"; x.beginPath(); x.arc(0, 0, r, 0, 6.3); x.fill();
    // 輝面: 右半円 + 明暗境界の半楕円(三日月はk<0.5で右側へ、凸型はk>0.5で左側へふくらむ)
    x.beginPath(); x.arc(0, 0, r, -Math.PI / 2, Math.PI / 2, false);
    x.ellipse(0, 0, Math.max(0.01, r * Math.abs(1 - 2 * k)), r, 0, Math.PI / 2, -Math.PI / 2, k < 0.5);
    x.closePath(); x.fillStyle = "#f3efd8"; x.fill();
    x.strokeStyle = "rgba(243,239,216,0.5)"; x.lineWidth = 1; x.beginPath(); x.arc(0, 0, r, 0, 6.3); x.stroke();
    x.restore();
  }

  function drawSkyObjects(x, f, proj, W, H, big, flip) {
    x.strokeStyle = "rgba(143,182,255,0.30)"; x.lineWidth = 1;
    LINES.forEach(function (ln) {
      var prev = null;
      ln.forEach(function (nm) {
        var s = f.stars[nm], q = s && s[1] > -3 ? proj(s[0], s[1]) : null;
        if (prev && q && Math.abs(prev[0] - q[0]) < W / 2) { x.beginPath(); x.moveTo(prev[0], prev[1]); x.lineTo(q[0], q[1]); x.stroke(); }
        prev = q;
      });
    });
    Object.keys(f.stars).forEach(function (nm) {
      var s = f.stars[nm]; if (s[1] < -1) return;
      var q = proj(s[0], s[1]); if (!q || q[0] < -10 || q[0] > W + 10 || q[1] < -10 || q[1] > H + 10) return;
      var mag = D.starmag[nm];
      if (nm === "アンドロメダ銀河") {
        x.fillStyle = "rgba(210,220,255,0.35)"; x.beginPath(); x.ellipse(q[0], q[1], 7, 3, -0.5, 0, 6.3); x.fill();
      } else if (nm === "すばる") {
        x.fillStyle = "rgba(190,215,255,0.95)";
        [[0, 0], [2.6, 1.5], [-2.4, 1.8], [1.2, -2.6], [-1, -2]].forEach(function (o) { x.beginPath(); x.arc(q[0] + o[0], q[1] + o[1], 1.1, 0, 6.3); x.fill(); });
      } else {
        x.fillStyle = nm === "ベテルギウス" || nm === "アンタレス" || nm === "アルデバラン" ? "#ffcfa8" : "#f4f7ff";
        x.beginPath(); x.arc(q[0], q[1], starR(mag), 0, 6.3); x.fill();
      }
      if (nm === "ポラリス(北極星)") {
        x.strokeStyle = "#8fb6ff"; x.lineWidth = 1.2; x.beginPath(); x.arc(q[0], q[1], 8, 0, 6.3); x.stroke();
      }
      if (LABEL[nm] || (big && LABEL[nm] === 0)) {
        x.fillStyle = "rgba(231,235,245,0.92)"; x.font = (big ? 12 : 11) + "px " + FONT;
        x.fillText(CLABEL[nm] || nm, q[0] + 8, q[1] - 6);
      }
    });
    Object.keys(f.planets).forEach(function (nm) {
      var s = f.planets[nm]; if (s[1] < 0.5) return;
      var q = proj(s[0], s[1]); if (!q) return;
      x.fillStyle = PCOL[nm]; x.beginPath(); x.arc(q[0], q[1], nm === "木星" ? 4.6 : 3.8, 0, 6.3); x.fill();
      x.fillStyle = PCOL[nm]; x.font = "bold " + (big ? 12 : 11) + "px " + FONT; x.fillText(nm, q[0] + 8, q[1] + 4);
    });
    var g = f.gc;
    if (g[1] > -1) {
      var qg = proj(g[0], g[1]);
      if (qg) { x.strokeStyle = "#e6c07a"; x.lineWidth = 1.2; x.beginPath(); x.arc(qg[0], qg[1], 6, 0, 6.3); x.stroke();
        x.fillStyle = "#e6c07a"; x.font = "11px " + FONT; x.fillText("天の川の中心", qg[0] + 10, qg[1] + 4); }
    }
    var m = f.moon;
    if (m && m.alt > -1) {
      var qm = proj(m.az, m.alt);
      if (qm) {
        drawMoon(x, qm, big ? 9 : 6, m, !!flip);
        x.fillStyle = "#f3efd8"; x.font = "bold " + (big ? 12 : 11) + "px " + FONT; x.fillText("月", qm[0] + 12, qm[1] + 4);
      }
    }
  }

  function drawPano(f) {
    var c = el("pano"), box = c.parentNode, W = Math.max(280, Math.floor(box.clientWidth)), FOV = W < 520 ? 100 : 120, AMAX = FOV / 2;
    var H = Math.round(W / 2);
    var x = setup(c, W, H), sx = W / FOV, sy = H / AMAX, cc = state.facing;
    var proj = function (az, alt) { return [W / 2 + wrap(az - cc) * sx, H - alt * sy]; };
    var gr = x.createLinearGradient(0, 0, 0, H); gr.addColorStop(0, "#04070f"); gr.addColorStop(1, "#16213a");
    x.fillStyle = gr; x.fillRect(0, 0, W, H);
    drawMW(x, f, proj, 13 * sx, W);
    drawSkyObjects(x, f, proj, W, H, true, false);
    if (state.fr) {
      var fr = state.fr, q = proj(fr.az, fr.alt);
      x.setLineDash([6, 4]); x.strokeStyle = "#e6c07a"; x.lineWidth = 1.5;
      x.strokeRect(q[0] - fr.w * sx / 2, q[1] - fr.h * sy / 2, fr.w * sx, fr.h * sy); x.setLineDash([]);
      x.fillStyle = "#e6c07a"; x.font = "11px " + MONO; x.fillText(fr.lens + "  " + fr.w + "°×" + fr.h + "°", q[0] - fr.w * sx / 2 + 6, q[1] - fr.h * sy / 2 + 14);
    }
    var half = FOV / 2 + 2, a;
    x.beginPath(); x.moveTo(0, H);
    for (a = -half; a <= half; a += 0.5) { var az = cc + a, h = HZ[((Math.round(az) % 360) + 360) % 360]; var p = proj(az, h); x.lineTo(p[0], p[1]); }
    x.lineTo(W, H); x.closePath(); x.fillStyle = "#04060b"; x.fill();
    x.strokeStyle = "rgba(143,182,255,0.35)"; x.lineWidth = 1; x.stroke();
    x.font = "bold 12px " + FONT;
    PEAKS.forEach(function (pk) {
      var d = wrap(pk.az - cc); if (Math.abs(d) > FOV / 2 - 4) return;
      var p = proj(pk.az, pk.alt);
      x.fillStyle = "#e6c07a"; x.fillText(pk.name + " " + pk.alt.toFixed(0) + "°", Math.min(W - 120, Math.max(4, p[0] - 30)), p[1] - 8);
    });
    var NAMES = { 0: "北", 45: "北東", 90: "東", 135: "南東", 180: "南", 225: "南西", 270: "西", 315: "北西" };
    x.fillStyle = "rgba(231,235,245,0.75)"; x.font = "11px " + MONO;
    for (a = 0; a < 360; a += 15) {
      var d2 = wrap(a - cc); if (Math.abs(d2) > FOV / 2 - 2) continue;
      var px = W / 2 + d2 * sx; x.fillRect(px, H - 6, 1, 6);
      if (NAMES[a] !== undefined) { x.fillText(NAMES[a] + " " + a + "°", px - 14, H - 10); }
    }
    x.fillStyle = "rgba(231,235,245,0.45)";
    for (var al = 15; al < AMAX; al += 15) { x.fillRect(0, H - al * sy, 8, 1); x.fillText(al + "°", 10, H - al * sy + 4); }
  }

  function drawAll(f) {
    var c = el("allsky"), box = c.parentNode, S = Math.max(260, Math.floor(box.clientWidth)), cx = S / 2, cy = S / 2, R = S / 2 - 22;
    var x = setup(c, S, S);
    var proj = function (az, alt) { if (alt < -8) return null; var r = R * (90 - alt) / 90, t = az * Math.PI / 180; return [cx - r * Math.sin(t), cy - r * Math.cos(t)]; };
    x.fillStyle = "#070b16"; x.fillRect(0, 0, S, S);
    x.save(); x.beginPath(); x.arc(cx, cy, R, 0, 6.3); x.clip();
    var gr = x.createRadialGradient(cx, cy, 0, cx, cy, R); gr.addColorStop(0, "#04070f"); gr.addColorStop(1, "#16213a");
    x.fillStyle = gr; x.fillRect(0, 0, S, S);
    x.fillStyle = "rgba(143,182,255,0.07)"; x.beginPath(); x.moveTo(cx, cy);
    var t0 = (state.facing - 60) * Math.PI / 180, t1 = (state.facing + 60) * Math.PI / 180, k;
    for (k = 0; k <= 24; k++) { var t = t0 + (t1 - t0) * k / 24; x.lineTo(cx - R * Math.sin(t), cy - R * Math.cos(t)); }
    x.closePath(); x.fill();
    drawMW(x, f, proj, R * 0.15, S);
    drawSkyObjects(x, f, proj, S, S, false, true);
    x.beginPath(); x.arc(cx, cy, R + 4, 0, 6.3);
    for (k = 359; k >= 0; k--) { var tt = k * Math.PI / 180, r = R * (90 - HZ[k]) / 90, px = cx - r * Math.sin(tt), py = cy - r * Math.cos(tt); if (k === 359) x.moveTo(px, py); else x.lineTo(px, py); }
    x.closePath(); x.fillStyle = "#04060b"; x.fill("evenodd");
    x.restore();
    x.strokeStyle = "rgba(143,182,255,0.4)"; x.lineWidth = 1; x.beginPath(); x.arc(cx, cy, R, 0, 6.3); x.stroke();
    x.beginPath(); x.arc(cx, cy, R * 0.5, 0, 6.3); x.strokeStyle = "rgba(143,182,255,0.12)"; x.stroke();
    x.fillStyle = "rgba(231,235,245,0.85)"; x.font = "bold 13px " + FONT;
    x.fillText("北", cx - 6, cy - R - 6); x.fillText("南", cx - 6, cy + R + 17); x.fillText("東", cx - R - 18, cy + 5); x.fillText("西", cx + R + 5, cy + 5);
  }

  function readout(f) {
    var hh = D.times[state.ti], pol = f.stars["ポラリス(北極星)"], gc = f.gc, m = f.moon;
    var cl = cloudAt(hh);
    var clT = cl === null ? "—" : cl + "%";
    var gcT = gc[1] > 0 ? "高度 " + gc[1].toFixed(0) + "° 方位 " + gc[0].toFixed(0) + "°" : "地平線の下";
    var moonT = m && m.alt > 0 ? "高度 " + m.alt.toFixed(0) + "° 方位 " + m.az.toFixed(0) + "° 輝面 " + Math.round(m.illum * 100) + "%" : "地平線の下";
    var box = el("readout"); box.textContent = "";
    [["雲量", clT], ["北極星", "高度 " + pol[1].toFixed(0) + "°"], ["天の川の中心", gcT], ["月", moonT]].forEach(function (kv) {
      var s = document.createElement("span"); s.appendChild(document.createTextNode(kv[0] + " "));
      var b = document.createElement("b"); b.textContent = kv[1]; s.appendChild(b); box.appendChild(s);
    });
  }

  function draw() {
    var f = D.frames[state.ti];
    el("timeLabel").textContent = D.times[state.ti];
    var btns = el("facing").querySelectorAll("button");
    Array.prototype.forEach.call(btns, function (b) { b.setAttribute("aria-pressed", String(+b.getAttribute("data-az") === state.facing)); });
    Array.prototype.forEach.call(document.querySelectorAll(".card"), function (cd) { cd.classList.toggle("on", cd.id === "card-" + state.card); });
    readout(f); drawAll(f); drawPano(f);
  }
  var rt; window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(draw, 120); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(draw);
  draw();
})();
