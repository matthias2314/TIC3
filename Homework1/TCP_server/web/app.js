/* =====================================================================
   Acquisition Monitor - app.js
   What the page DOES. Sections:
     1. Elements and page state      5. Messages from the server (/events)
     2. Formatting helpers           6. Updating the page
     3. The form                     7. The chart (hand-drawn on a canvas)
     4. Start and Stop               8. Start-up
   The server side is web_server.py. Talking to it:
     page -> server   fetch('/start') and fetch('/stop')   (normal requests)
     server -> page   new EventSource('/events')           (a stream that
                      stays open; the server writes an event whenever
                      something happens: status, session, samples, summary)
   ===================================================================== */
"use strict";


/* ---------------------------------------------------------------------
   1. ELEMENTS AND PAGE STATE
   --------------------------------------------------------------------- */
const $ = (id) => document.getElementById(id);

const ui = {
  // header
  state: $("state"), stateLabel: $("state-label"),
  stateProgress: $("state-progress"), stateBar: $("state-bar-fill"),
  indRpi: $("ind-rpi"), indRpiText: $("ind-rpi-text"),
  indEsp: $("ind-esp"), indEspText: $("ind-esp-text"),
  // form
  form: $("config-form"), rate: $("rate"), range: $("range"),
  sensitivity: $("sensitivity"),
  fieldSamples: $("field-samples"), samples: $("samples"),
  fieldDuration: $("field-duration"), duration: $("duration"),
  btnStart: $("btn-start"), btnStop: $("btn-stop"),
  // plot and cards
  plot: $("plot"),
  valAx: $("val-ax"), valAy: $("val-ay"), valAz: $("val-az"), valDt: $("val-dt"),
  // status
  cfgLine1: $("cfg-line1"), cfgLine2: $("cfg-line2"),
  errorBox: $("error-box"), errorText: $("error-text"),
  // summary
  summary: $("summary"), sumFile: $("sum-file"), sumNote: $("sum-note"),
  // timing
  timeExpected: $("time-expected"), timeMean: $("time-mean"), timeJitter: $("time-jitter"),
};

const STATE_TEXT = {
  waiting: "Waiting", ready: "Ready", running: "Running",
  finished: "Finished", error: "Error",
};

// What the page knows right now
const page = {
  serverConnected: false,  // the /events stream is open
  espConnected: false,     // the server says the ESP32 is connected
  state: "waiting",        // waiting | ready | running | finished | error
  busy: false,             // a /start or /stop request is on its way
  stopSent: false,         // Stop was pressed in this session
};


/* ---------------------------------------------------------------------
   2. FORMATTING HELPERS
   --------------------------------------------------------------------- */
const DASH = "—";

/** +0.42 / -1.07: always with a sign, so the columns don't jump */
function signed(value) {
  return (value >= 0 ? "+" : "") + value.toFixed(2);
}

/** A number with fixed decimals, or a dash when there is no value */
function fixed(value, decimals) {
  return value === null || value === undefined ? DASH : value.toFixed(decimals);
}

/** "350 / 1000" or "3.2 / 10 s" */
function progressText(progress) {
  if (!progress) return "";
  if (progress.unit === "s") {
    return `${progress.done.toFixed(1)} / ${progress.total} s`;
  }
  return `${progress.done} / ${progress.total}`;
}

/** The two lines of "Current configuration" */
function configLines(config) {
  const mode = config.mode === "parallel" ? "Parallel" : "Sequential";
  const line1 = `${config.transport.toUpperCase()} · ${mode} · ${config.rate_hz} Hz · ±${config.range_g} g`;
  const line2 = config.stop === "time"
    ? `Stop by time: T = ${config.duration_s} s`
    : `Stop by samples: N = ${config.num_samples}`;
  return [line1, line2];
}


/* ---------------------------------------------------------------------
   3. THE FORM
   --------------------------------------------------------------------- */
function selectedRadio(name) {
  return ui.form.querySelector(`input[name="${name}"]:checked`).value;
}

/** Sensitivity: how many mg one raw unit is worth, for the chosen range.
    The raw value is an int16: ±32768 units cover ±range g. */
function updateSensitivity() {
  const mgPerLsb = (Number(ui.range.value) * 1000) / 32768;
  ui.sensitivity.textContent = `${mgPerLsb.toFixed(3)} mg/LSB`;
}

/** The field that is NOT chosen in "Stop by" is calculated from the other:
    N = round(T × rate)  or  T = N / rate. It's only an estimate.
    If the chosen field is empty or not a number, the other one is left empty. */
function updateDerived() {
  const rate = Number(ui.rate.value);
  const byTime = selectedRadio("stop") === "time";
  if (byTime) {
    const seconds = readNumber(ui.duration);
    ui.samples.value = Number.isFinite(seconds) ? Math.round(seconds * rate) : "";
  } else {
    const samples = readNumber(ui.samples);
    ui.duration.value = Number.isFinite(samples) ? (samples / rate).toFixed(2) : "";
  }
  ui.fieldSamples.classList.toggle("is-derived", byTime);
  ui.fieldDuration.classList.toggle("is-derived", !byTime);
}

/** Expected interval = 1 / rate, shown before a session starts */
function updateExpectedInterval() {
  if (page.state !== "running") {
    ui.timeExpected.textContent = (1000 / Number(ui.rate.value)).toFixed(2);
  }
}

/** Typing in a field makes it the one that ends the session */
function chooseStop(value) {
  ui.form.querySelector(`input[name="stop"][value="${value}"]`).checked = true;
  updateDerived();
}

/** The number typed in a field, or NaN if it's empty or not a number.
    (Number("") would be 0, which would hide an empty field.) */
function readNumber(input) {
  return input.value.trim() === "" ? NaN : Number(input.value);
}

const MAX_SECONDS = 3600;          // the ESP32 accepts sessions of up to 1 hour

/** Check the field that ends the session. Returns a message for the user,
    or null if everything is fine. Only the chosen field is checked: the
    other one is just an estimate and is not sent to the ESP32. */
function formProblem() {
  if (selectedRadio("stop") === "time") {
    const seconds = readNumber(ui.duration);
    if (!Number.isFinite(seconds) || seconds <= 0) {
      return "Duration (T) must be a number of seconds greater than 0";
    }
    if (seconds > MAX_SECONDS) {
      return `Duration (T) can be at most ${MAX_SECONDS} s (1 hour)`;
    }
    if (Math.round(seconds * 1000) < 1) {
      return "Duration (T) must be at least 0.001 s";
    }
  } else {
    const samples = readNumber(ui.samples);
    if (!Number.isInteger(samples) || samples < 1) {
      return "Samples (N) must be a whole number, 1 or more";
    }
    if (samples > 4294967295) {
      return "Samples (N) is too large";
    }
  }
  return null;
}

/** Everything the server needs for /start (web_server.py: config_from_form) */
function readForm() {
  return {
    transport: selectedRadio("transport"),
    mode: selectedRadio("mode"),
    rate: ui.rate.value,
    range: ui.range.value,
    stop: selectedRadio("stop"),
    samples: ui.samples.value,
    duration: ui.duration.value,
  };
}

/** The settings can't change while a session runs */
function setFormEnabled(enabled) {
  for (const input of ui.form.querySelectorAll("input, select")) {
    input.disabled = !enabled;
  }
}

ui.range.addEventListener("change", updateSensitivity);
ui.rate.addEventListener("change", () => { updateDerived(); updateExpectedInterval(); });
for (const radio of ui.form.querySelectorAll('input[name="stop"]')) {
  radio.addEventListener("change", updateDerived);
}
ui.samples.addEventListener("input", () => chooseStop("samples"));
ui.duration.addEventListener("input", () => chooseStop("time"));


/* ---------------------------------------------------------------------
   4. START AND STOP
   --------------------------------------------------------------------- */
/** POST some JSON and return the answer. Throws an Error with the
    server's message if it said no. */
async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const answer = await response.json();
  if (!response.ok) {
    throw new Error(answer.error || `HTTP ${response.status}`);
  }
  return answer;
}

// Start is the form's submit button: pressing it (or Enter) submits the form
ui.form.addEventListener("submit", async (event) => {
  event.preventDefault();              // don't reload the page (the browser's default)
  const problem = formProblem();
  if (problem) {                       // say what's wrong instead of sending it
    showError(problem);
    return;
  }
  page.busy = true;
  updateButtons();
  try {
    await post("/start", readForm());
    // Nothing else to do here: the server answers with events (section 5)
  } catch (error) {
    showError(error.message);
  } finally {
    page.busy = false;
    updateButtons();
  }
});

ui.btnStop.addEventListener("click", async () => {
  page.stopSent = true;
  updateButtons();
  try {
    await post("/stop");
  } catch (error) {
    showError(error.message);
  }
});


/* ---------------------------------------------------------------------
   5. MESSAGES FROM THE SERVER (/events)
   EventSource keeps the connection open and reconnects by itself if it
   drops. Each addEventListener("name") receives the events with that name.
   --------------------------------------------------------------------- */
function connect() {
  const events = new EventSource("/events");

  events.onopen = () => {
    page.serverConnected = true;
    updateHeader();
  };

  events.onerror = () => {
    // The server stopped (or the network dropped). The browser keeps trying.
    page.serverConnected = false;
    page.espConnected = false;
    updateHeader();
  };

  // The general status: sent on connecting, and whenever it changes
  events.addEventListener("status", (event) => {
    const status = JSON.parse(event.data);
    page.state = status.state;
    page.espConnected = status.esp !== null;
    if (status.state !== "running") page.stopSent = false;

    if (status.config) {
      [ui.cfgLine1.textContent, ui.cfgLine2.textContent] = configLines(status.config);
    }
    if (status.file) ui.sumFile.textContent = status.file;
    if (status.state === "running") {      // also for a page opened mid-session
      showSummary(null);
      ui.sumNote.textContent = "Session in progress…";
    }
    status.error ? showError(status.error) : clearError();
    updateHeader(status.progress);
  });

  // A new session starts: clean everything that belongs to the previous one
  events.addEventListener("session", (event) => {
    const session = JSON.parse(event.data);
    page.stopSent = false;
    chart.start();
    for (const value of [ui.valAx, ui.valAy, ui.valAz, ui.valDt]) value.textContent = DASH;
    ui.timeExpected.textContent = session.expected_interval_ms.toFixed(2);
    ui.timeMean.textContent = DASH;
    ui.timeJitter.textContent = DASH;
    showSummary(null);
    ui.sumFile.textContent = session.file;
    ui.sumNote.textContent = "Session in progress…";
  });

  // A batch of samples (about 10 per second)
  events.addEventListener("samples", (event) => {
    const batch = JSON.parse(event.data);
    chart.add(batch);

    const latest = batch.latest;
    ui.valAx.textContent = signed(latest.ax);
    ui.valAy.textContent = signed(latest.ay);
    ui.valAz.textContent = signed(latest.az);
    ui.valDt.textContent = fixed(latest.dt_ms, 2);
    ui.timeMean.textContent = fixed(batch.timing.mean_ms, 2);
    ui.timeJitter.textContent = fixed(batch.timing.jitter_ms, 2);
    updateProgress(batch.progress);
  });

  // The session ended: the final counters
  events.addEventListener("summary", (event) => {
    showSummary(JSON.parse(event.data));
  });
}


/* ---------------------------------------------------------------------
   6. UPDATING THE PAGE
   The look of each state is in style.css; here we only switch classes.
   --------------------------------------------------------------------- */
function setIndicator(indicator, text, connected) {
  indicator.classList.toggle("is-connected", connected);
  indicator.classList.toggle("is-disconnected", !connected);
  text.textContent = connected ? "connected" : "disconnected";
}

function updateHeader(progress) {
  setIndicator(ui.indRpi, ui.indRpiText, page.serverConnected);
  setIndicator(ui.indEsp, ui.indEspText, page.espConnected);

  // Without the server we don't know anything: show "waiting"
  const state = page.serverConnected ? page.state : "waiting";
  ui.state.className = `state state--${state}`;
  ui.stateLabel.textContent = STATE_TEXT[state];
  if (state === "running" || state === "finished") {
    updateProgress(progress);
  } else {
    ui.stateProgress.textContent = "";
    ui.stateBar.style.width = "0%";
  }
  updateButtons();
}

function updateProgress(progress) {
  if (!progress) return;
  ui.stateProgress.textContent = progressText(progress);
  const fraction = progress.total > 0 ? Math.min(progress.done / progress.total, 1) : 0;
  ui.stateBar.style.width = `${(fraction * 100).toFixed(1)}%`;
}

/** Start: only with the server and the ESP32 there, and nothing running.
    Stop: only while running, and only once. */
function updateButtons() {
  const running = page.state === "running";
  const canStart = page.serverConnected && page.espConnected && !running && !page.busy;
  ui.btnStart.disabled = !canStart;
  ui.btnStop.disabled = !(page.serverConnected && running && !page.stopSent);
  setFormEnabled(!running);
}

function showError(text) {
  ui.errorBox.classList.add("is-error");
  ui.errorBox.querySelector(".error-icon").textContent = "!";
  ui.errorText.textContent = text;
}

function clearError() {
  ui.errorBox.classList.remove("is-error");
  ui.errorBox.querySelector(".error-icon").textContent = "✓";
  ui.errorText.textContent = "No errors";
}

/** Fill the summary, or show the dashes when stats is null */
function showSummary(stats) {
  const fields = ["expected", "received", "late", "duplicates", "lost"];
  for (const name of fields) {
    $(`sum-${name}`).textContent = stats ? stats[name] : DASH;
  }
  $("sum-loss").textContent = stats ? stats.loss_pct.toFixed(1) : DASH;
  ui.summary.classList.toggle("is-empty", !stats);

  if (stats) {
    ui.sumFile.textContent = stats.file;
    ui.sumNote.textContent = stats.note;
    // A session that didn't complete gets the warning colour
    // (result: completed | stopped | failed | interrupted, see data_channel.py)
    ui.sumNote.classList.toggle("note-warning", stats.result !== "completed");
  } else {
    ui.sumNote.classList.remove("note-warning");
  }
}

/** index.html contains example values, so its look can be checked without
    a server. Replace them with the real "nothing yet" state on load. */
function resetPage() {
  for (const value of [ui.valAx, ui.valAy, ui.valAz, ui.valDt, ui.timeMean, ui.timeJitter]) {
    value.textContent = DASH;
  }
  ui.cfgLine1.textContent = DASH;
  ui.cfgLine2.textContent = "";
  ui.sumFile.textContent = DASH;
  showSummary(null);
  ui.sumNote.textContent = DASH;
  clearError();
  updateSensitivity();
  updateDerived();
  updateExpectedInterval();
  updateHeader();
}


/* ---------------------------------------------------------------------
   7. THE CHART
   A <canvas> is only pixels: we draw the grid, the numbers and the three
   lines ourselves. Values become pixel positions with a linear "scale":
       x_pixel = left + (t - tMin) / (tMax - tMin) * width
       y_pixel = top  + (yMax - a) / (yMax - yMin) * height
   (y grows DOWNWARD on a canvas, that's why it is yMax - a).
   --------------------------------------------------------------------- */
const WINDOW_S = 10;                 // seconds shown; older points scroll out
const MARGIN = { left: 50, right: 14, top: 12, bottom: 36 };   // room for the numbers
const Y_MARGIN = 0.1;                // 10 % free space above and below the data
const Y_SHRINK = 0.15;               // how fast the axis shrinks back (per frame)

const chart = {
  canvas: null,
  ctx: null,
  t: [], ax: [], ay: [], az: [],     // the points on screen
  yMin: null, yMax: null,            // the y axis being shown
  drawPending: false,
  colors: null,

  /** A new session: create the canvas the first time, then empty it */
  start() {
    if (!this.canvas) {
      this.canvas = document.createElement("canvas");
      ui.plot.appendChild(this.canvas);       // the placeholder text disappears (CSS :empty)
      ui.plot.classList.add("has-chart");
      this.ctx = this.canvas.getContext("2d");
      this.readColors();
      // Redraw at the right size whenever the box changes size
      new ResizeObserver(() => this.resize()).observe(ui.plot);
      this.resize();
    }
    this.t = []; this.ax = []; this.ay = []; this.az = [];
    this.yMin = null;
    this.yMax = null;
    this.requestDraw();
  },

  /** Colours come from style.css, so there is only one place to change them */
  readColors() {
    const css = getComputedStyle(document.documentElement);
    const get = (name) => css.getPropertyValue(name).trim();
    this.colors = {
      ax: get("--axis-x"), ay: get("--axis-y"), az: get("--axis-z"),
      grid: get("--border"), zero: get("--border-strong"), text: get("--text-label"),
    };
    this.font = `12px ${getComputedStyle(document.body).fontFamily}`;
  },

  add(batch) {
    if (!this.canvas) this.start();   // page opened in the middle of a session
    this.t.push(...batch.t);
    this.ax.push(...batch.ax);
    this.ay.push(...batch.ay);
    this.az.push(...batch.az);

    // Drop the points that scrolled out of the window
    const oldest = this.t[this.t.length - 1] - WINDOW_S;
    let drop = 0;
    while (drop < this.t.length && this.t[drop] < oldest) drop++;
    if (drop > 0) {
      for (const list of [this.t, this.ax, this.ay, this.az]) list.splice(0, drop);
    }
    this.requestDraw();
  },

  /** Make the canvas as many REAL pixels as the box has. On a Retina screen
      one CSS pixel is 2 screen pixels (devicePixelRatio = 2); without this
      the lines would look blurry. */
  resize() {
    const ratio = window.devicePixelRatio || 1;
    this.width = ui.plot.clientWidth;
    this.height = ui.plot.clientHeight;
    this.canvas.width = Math.round(this.width * ratio);
    this.canvas.height = Math.round(this.height * ratio);
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);   // draw in CSS pixels from now on
    this.requestDraw();
  },

  /** Draw at the next screen refresh, at most once per refresh,
      however many batches arrive in between */
  requestDraw() {
    if (!this.drawPending) {
      this.drawPending = true;
      requestAnimationFrame(() => this.draw());
    }
  },

  /** Automatic y axis: follows the data with a margin. It grows at once
      (nothing is ever cut off) and shrinks slowly (it doesn't jump). */
  updateYAxis() {
    let low = Infinity;
    let high = -Infinity;
    for (const list of [this.ax, this.ay, this.az]) {
      for (const v of list) {
        if (v < low) low = v;
        if (v > high) high = v;
      }
    }
    if (low === Infinity) { low = -1; high = 1; }      // no data yet

    const span = Math.max(high - low, 0.5);            // at least 0.5 m/s² tall
    const targetMin = low - span * Y_MARGIN;
    const targetMax = high + span * Y_MARGIN;

    if (this.yMin === null) {
      this.yMin = targetMin;
      this.yMax = targetMax;
      return false;
    }
    this.yMin = targetMin < this.yMin ? targetMin : this.yMin + (targetMin - this.yMin) * Y_SHRINK;
    this.yMax = targetMax > this.yMax ? targetMax : this.yMax + (targetMax - this.yMax) * Y_SHRINK;
    // Still moving? Then another frame is needed
    return Math.abs(targetMin - this.yMin) + Math.abs(targetMax - this.yMax) > span * 0.01;
  },

  draw() {
    this.drawPending = false;
    const ctx = this.ctx;
    const left = MARGIN.left;
    const top = MARGIN.top;
    const width = this.width - MARGIN.left - MARGIN.right;
    const height = this.height - MARGIN.top - MARGIN.bottom;
    ctx.clearRect(0, 0, this.width, this.height);
    if (width <= 0 || height <= 0) return;

    // Time axis: grows from 0 until WINDOW_S, then scrolls
    const tLast = this.t.length ? this.t[this.t.length - 1] : 0;
    const tMin = Math.max(0, tLast - WINDOW_S);
    const tMax = Math.max(tMin + 1, tLast);

    const stillMoving = this.updateYAxis();
    const yMin = this.yMin;
    const yMax = this.yMax;

    // The scale: value -> pixel
    const xPixel = (t) => left + ((t - tMin) / (tMax - tMin)) * width;
    const yPixel = (a) => top + ((yMax - a) / (yMax - yMin)) * height;

    ctx.font = this.font;
    ctx.lineWidth = 1;

    // Horizontal grid lines and the y numbers
    const yStep = niceStep((yMax - yMin) / 5);
    const yDecimals = decimalsFor(yStep);
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    // Count in whole steps (k) and multiply: adding 0.1 again and again
    // drifts (0.30000000000000004) and could print "-0.0"
    for (let k = Math.ceil(yMin / yStep); k * yStep <= yMax; k++) {
      const a = k * yStep;
      const y = Math.round(yPixel(a)) + 0.5;           // +0.5: a sharp 1-pixel line
      ctx.strokeStyle = k === 0 ? this.colors.zero : this.colors.grid;   // the 0 line stands out
      line(ctx, left, y, left + width, y);
      ctx.fillStyle = this.colors.text;
      ctx.fillText(a.toFixed(yDecimals), left - 8, y);
    }

    // Vertical grid lines and the time numbers
    const tStep = niceStep((tMax - tMin) / 6);
    const tDecimals = decimalsFor(tStep);
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let k = Math.ceil(tMin / tStep - 1e-9); k * tStep <= tMax + 1e-9; k++) {
      const t = k * tStep;
      const x = Math.round(xPixel(t)) + 0.5;
      ctx.strokeStyle = this.colors.grid;
      line(ctx, x, top, x, top + height);
      ctx.fillStyle = this.colors.text;
      ctx.fillText(t.toFixed(tDecimals), x, top + height + 6);
    }
    ctx.fillText("Time (s)", left + width / 2, top + height + 21);

    // The three lines, clipped to the plot area
    ctx.save();
    ctx.beginPath();
    ctx.rect(left, top, width, height);
    ctx.clip();
    ctx.lineWidth = 1.5;
    ctx.lineJoin = "round";
    // With more points than pixels, drawing all of them only costs time:
    // take one every `step` (at most ~2 per pixel column)
    const step = Math.max(1, Math.floor(this.t.length / (width * 2)));
    for (const axis of ["ax", "ay", "az"]) {
      const values = this[axis];
      ctx.strokeStyle = this.colors[axis];
      ctx.beginPath();
      for (let i = 0; i < values.length; i += step) {
        const x = xPixel(this.t[i]);
        const y = yPixel(values[i]);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.restore();

    if (stillMoving) this.requestDraw();
  },
};

/** A straight line from (x1, y1) to (x2, y2) */
function line(ctx, x1, y1, x2, y2) {
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}

/** A "round" step near `raw`: 1, 2 or 5 times a power of ten
    (0.1, 0.2, 0.5, 1, 2, 5, 10, ...), so the axis shows 2, 4, 6
    instead of 1.73, 3.46, 5.19 */
function niceStep(raw) {
  const power = Math.pow(10, Math.floor(Math.log10(raw)));
  const fraction = raw / power;               // between 1 and 10
  const nice = fraction < 1.5 ? 1 : fraction < 3.5 ? 2 : fraction < 7.5 ? 5 : 10;
  return nice * power;
}

/** Decimals needed to write multiples of `step` (0.5 -> 1, 2 -> 0) */
function decimalsFor(step) {
  return Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
}


/* ---------------------------------------------------------------------
   8. START-UP
   --------------------------------------------------------------------- */
resetPage();
connect();
