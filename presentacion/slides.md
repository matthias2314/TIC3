---
title: Adquisición remota de aceleración
info: TIC3 · Tarea 1 · ESP32-S3 + BMI270 → Raspberry Pi
colorSchema: dark
aspectRatio: 16/9
canvasWidth: 980
fonts:
  sans: Inter
  mono: DejaVu Sans Mono
  provider: none
lineNumbers: true
transition: fade
drawings:
  persist: false
---

<div class="cover-wrap">
<div>
  <div class="kicker">TIC3 · Tarea 1</div>
  <div class="cover-title">Adquisición remota<br>de <span class="accent">aceleración</span></div>
  <div class="cover-sub">ESP32-S3 + BMI270 → Raspberry Pi<br>TCP / UDP · GUI web</div>
  <div class="cover-meta">
    Matthias Aliaga · <span class="faint">[nombre del compañero/a]</span><br>
    15 de octubre de 2026
  </div>
</div>
<div class="cover-art">
  <div class="chip-box"><carbon-activity /></div>
  <span class="sep"><carbon-arrow-right /></span>
  <div class="chip-box"><carbon-chip /></div>
  <span class="sep"><carbon-wifi /></span>
  <div class="chip-box"><carbon-bare-metal-server /></div>
</div>
</div>

---

<div class="kicker">02 · Topología</div>

# Diagrama de <span class="accent">bloques</span>

<div class="topo">
<svg class="topo-lines" viewBox="0 0 884 360">
  <defs>
    <marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#4cc3ff"/></marker>
    <marker id="ag" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#8494ad"/></marker>
  </defs>
  <!-- físico -->
  <line x1="88" y1="193" x2="163" y2="193" class="phys" />
  <text x="125" y="183" class="lbl-s" text-anchor="middle">I²C</text>
  <text x="125" y="212" class="lbl-xs" text-anchor="middle">400 kHz</text>
  <line x1="352" y1="313" x2="483" y2="313" class="phys" />
  <text x="417" y="303" class="lbl-s" text-anchor="middle">Wi-Fi 2.4 GHz</text>
  <text x="417" y="334" class="lbl-xs" text-anchor="middle">WPA2</text>
  <line x1="720" y1="253" x2="768" y2="253" class="phys" />
  <!-- interno -->
  <line x1="257" y1="168" x2="257" y2="158" class="inner" marker-end="url(#ag)"/>
  <line x1="595" y1="158" x2="595" y2="168" class="inner" marker-end="url(#ag)"/>
  <!-- lógico -->
  <g v-click>
    <line x1="352" y1="73" x2="483" y2="73" class="logic" marker-start="url(#ah)" marker-end="url(#ah)"/>
    <text x="417" y="64" class="lbl" text-anchor="middle">TCP</text>
    <line x1="352" y1="133" x2="481" y2="133" class="logic dash" marker-end="url(#ah)"/>
    <text x="417" y="124" class="lbl" text-anchor="middle">TCP o UDP</text>
    <text x="745" y="241" class="lbl" text-anchor="middle">HTTP</text>
  </g>
</svg>

<div class="blk solo" style="left:0; top:146px; width:88px; height:94px;">
  <carbon-activity class="ic" /><b>BMI270</b><span>FIFO 2 KB</span>
</div>

<div class="grp" style="left:150px; width:215px;"><div class="grp-h"><carbon-chip /> ESP32-S3 · <i>cliente</i></div></div>
<div class="blk" style="left:163px; top:50px;">socket control</div>
<div class="blk" style="left:163px; top:110px;">socket datos</div>
<div class="blk" style="left:163px; top:170px;"><code>fifo_take</code> + <code>seq</code>, <code>t_us</code></div>
<div class="blk" style="left:163px; top:230px;">FreeRTOS · 1 o 2 tareas</div>
<div class="blk" style="left:163px; top:290px;">Wi-Fi estación · DHCP</div>

<div class="grp" style="left:470px; width:250px;"><div class="grp-h"><carbon-bare-metal-server /> Raspberry Pi · <i>servidor</i></div></div>
<div class="blk w2" style="left:483px; top:50px;">control <code>:10001</code></div>
<div class="blk w2" style="left:483px; top:110px;">datos <code>:10000</code></div>
<div class="blk w2" style="left:483px; top:170px;"><code>SampleTracker</code> → CSV</div>
<div class="blk w2" style="left:483px; top:230px;">GUI web <code>:8080</code></div>
<div class="blk w2" style="left:483px; top:290px;">Access point · IP fija</div>

<div class="blk solo" style="left:770px; top:216px; width:114px; height:74px;">
  <carbon-laptop class="ic" /><b>Navegador</b>
</div>
</div>

<div class="topo-legend">
  <span><i class="sw phys"></i>enlace físico</span>
  <span><i class="sw logic"></i>canal lógico (socket)</span>
  <span><i class="sw logic dash"></i>transporte elegible (RF6)</span>
</div>

---

<div class="kicker">03 · Una sesión</div>

# Una sesión, <span class="accent">mensaje por mensaje</span>

<div class="seq">
  <div class="head" style="left:10%">Navegador</div>
  <div class="head" style="left:50%">Raspberry Pi</div>
  <div class="head" style="left:90%">ESP32</div>
  <div class="life" style="left:10%"></div><div class="life" style="left:50%"></div><div class="life" style="left:90%"></div>
  <div class="rows">
    <div class="row" v-click><div class="msg l " style="left:50%; width:40%"><span class="lbl">connect :10001 · control (al encender)</span></div></div>
    <div class="row" v-click><div class="msg r " style="left:10%; width:40%"><span class="lbl">POST /start</span></div></div>
    <div class="row" v-click><div class="msg r " style="left:50%; width:40%"><span class="lbl">CONFIG · 9 B</span></div></div>
    <div class="row" v-click><div class="msg l " style="left:50%; width:40%"><span class="lbl">ACK · 1 B (0 = OK)</span></div></div>
    <div class="row" v-click><div class="msg l " style="left:50%; width:40%"><span class="lbl">canal de datos :10000 · TCP o UDP</span></div></div>
    <div class="row" v-click><div class="msg l dash" style="left:50%; width:40%"><span class="lbl">muestras · 14 B cada una · cada 5 ms</span></div></div>
    <div class="row" v-click><div class="msg r opt" style="left:10%; width:40%"><span class="lbl">POST /stop (opcional)</span></div></div>
    <div class="row" v-click><div class="msg r opt" style="left:50%; width:40%"><span class="lbl">STOP · 0xFE (opcional)</span></div></div>
    <div class="row" v-click><div class="msg l " style="left:50%; width:40%"><span class="lbl">END · 6 B (cómo terminó + total)</span></div></div>
    <div class="row" v-click><div class="msg l " style="left:10%; width:40%"><span class="lbl">resumen (Server-Sent Events)</span></div></div>
  </div>
</div>

---

<div class="kicker">04 · Protocolo</div>

# Mensajes binarios <span class="accent">de tamaño fijo</span>

<div class="proto">
<div class="prow ruler"><div class="pl"></div><div class="pgrid"><div class="r">0</div><div class="r">1</div><div class="r">2</div><div class="r">3</div><div class="r">4</div><div class="r">5</div><div class="r">6</div><div class="r">7</div><div class="r">8</div><div class="r">9</div><div class="r">10</div><div class="r">11</div><div class="r">12</div><div class="r">13</div></div></div>
<div class="prow"><div class="pl"><b>CONFIG</b> <span class="sz">9 B</span><span class="dir pi">Pi <carbon-arrow-right /> ESP32 · control</span></div><div class="pgrid"><div class="f s1" style="grid-column: span 1">rango<small>g</small></div><div class="f s1" style="grid-column: span 1">odr</div><div class="f s1" style="grid-column: span 1">transp</div><div class="f s1" style="grid-column: span 1">modo</div><div class="f s1" style="grid-column: span 1">fin</div><div class="f " style="grid-column: span 4">límite<small>N muestras o ms</small></div></div></div>
<div class="prow" v-click><div class="pl"><b>ACK</b> <span class="sz">1 B</span><span class="dir esp">ESP32 <carbon-arrow-right /> Pi · control</span></div><div class="pgrid"><div class="f s1" style="grid-column: span 1">0–7<small>estado</small></div></div></div>
<div class="prow" v-click><div class="pl"><b>DATA</b> <span class="sz">14 B</span><span class="dir esp">ESP32 <carbon-arrow-right /> Pi · datos</span></div><div class="pgrid"><div class="f data" style="grid-column: span 4">seq<small>uint32</small></div><div class="f data" style="grid-column: span 4">t_us<small>uint32 · µs</small></div><div class="f data" style="grid-column: span 2">ax<small>int16</small></div><div class="f data" style="grid-column: span 2">ay<small>int16</small></div><div class="f data" style="grid-column: span 2">az<small>int16</small></div></div></div>
<div class="prow" v-click><div class="pl"><b>STOP</b> <span class="sz">1 B</span><span class="dir pi">Pi <carbon-arrow-right /> ESP32 · control</span></div><div class="pgrid"><div class="f code" style="grid-column: span 1">0xFE</div></div></div>
<div class="prow" v-click><div class="pl"><b>END</b> <span class="sz">6 B</span><span class="dir esp">ESP32 <carbon-arrow-right /> Pi · control</span></div><div class="pgrid"><div class="f code" style="grid-column: span 1">0xFF</div><div class="f s1" style="grid-column: span 1">fin<small>0/1/2</small></div><div class="f " style="grid-column: span 4">total<small>muestras tomadas</small></div></div></div>
</div>

<p class="faint proto-foot" style="margin-top: 26px;">1 casilla = 1 byte · little-endian · sin relleno (<code>packed</code> en C, <code>'&lt;'</code> en Python)</p>

---

<div class="kicker">05 · El límite</div>

# Una muestra a la vez: <span class="accent">1600 Hz es inalcanzable</span>

<div class="hchart">
  <div class="hb-axis"><span style="left:0px">0</span><span style="left:133px">400</span><span style="left:267px">800</span><span style="left:400px">1200</span><span style="left:533px">1600</span></div>
  <div class="vline req" style="left:533px"><span>pedido · 1600</span></div>
  <div class="vline tick" v-click="3" style="left:333px"><span>techo del tick ≈ 1000</span></div>
<div class="hb">
  <div class="hb-l"><b>Método del profesor · I²C 100 kHz</b><span>una muestra por lectura</span></div>
  <div class="hb-track"><div class="hb-bar bad" style="width:117px"></div><span class="hb-v bad" style="left:127px">≈ 350 /s · medido</span></div>
</div>
<div class="hb" v-click>
  <div class="hb-l"><b>Método del profesor · I²C 400 kHz</b><span>una muestra por lectura</span></div>
  <div class="hb-track"><div class="hb-bar est" style="width:167px"></div><span class="hb-v est" style="left:177px">≈ 500 /s · estimado</span></div>
</div>
  <div class="hb hb-gap"></div>
<div class="hb" v-click>
  <div class="hb-l"><b>Nuestro · FIFO + 400 kHz</b><span>≈ 8 muestras por lectura</span></div>
  <div class="hb-track"><div class="hb-bar ok" style="width:539px"></div><span class="hb-v ok" style="left:549px">1617 /s · medido</span></div>
</div>
</div>

<div class="hchart-foot">
  <span v-click="3"><code>vTaskDelay(1)</code> = 1 tick = 1 ms → ≈ 1 muestra por tick</span>
  <span v-click="4">sin FIFO: muestra no leída a tiempo = <b>sobrescrita</b>, y nadie se entera</span>
</div>

---

<div class="kicker">06 · Por qué</div>

# Cada muestra tiene <span class="accent">0.625 ms</span> de presupuesto

<svg class="tl" viewBox="0 0 884 230">
  <line x1="120.0" y1="18" x2="120.0" y2="200" class="grid"/><line x1="198.1" y1="18" x2="198.1" y2="200" class="grid"/><line x1="276.2" y1="18" x2="276.2" y2="200" class="grid"/><line x1="354.4" y1="18" x2="354.4" y2="200" class="grid"/><line x1="432.5" y1="18" x2="432.5" y2="200" class="grid"/><line x1="510.6" y1="18" x2="510.6" y2="200" class="grid"/><line x1="588.8" y1="18" x2="588.8" y2="200" class="grid"/><line x1="666.9" y1="18" x2="666.9" y2="200" class="grid"/><line x1="745.0" y1="18" x2="745.0" y2="200" class="grid"/><line x1="823.1" y1="18" x2="823.1" y2="200" class="grid"/>
  <text x="0" y="45" class="rl">sensor</text>
  <circle cx="120.0" cy="40" r="7" class="smp"/><circle cx="198.1" cy="40" r="7" class="smp"/><circle cx="276.2" cy="40" r="7" class="smp"/><circle cx="354.4" cy="40" r="7" class="smp"/><circle cx="432.5" cy="40" r="7" class="smp"/><circle cx="510.6" cy="40" r="7" class="smp"/><circle cx="588.8" cy="40" r="7" class="smp"/><circle cx="666.9" cy="40" r="7" class="smp"/><circle cx="745.0" cy="40" r="7" class="smp"/><circle cx="823.1" cy="40" r="7" class="smp"/>
  <g v-click="1">
    <text x="0" y="105" class="rl">sin FIFO</text>
    <circle cx="120.0" cy="100" r="7" class="okc"/><g class="lost"><circle cx="198.1" cy="100" r="7"/><line x1="193.1" y1="95" x2="203.1" y2="105"/><line x1="193.1" y1="105" x2="203.1" y2="95"/></g><g class="lost"><circle cx="276.2" cy="100" r="7"/><line x1="271.2" y1="95" x2="281.2" y2="105"/><line x1="271.2" y1="105" x2="281.2" y2="95"/></g><g class="lost"><circle cx="354.4" cy="100" r="7"/><line x1="349.4" y1="95" x2="359.4" y2="105"/><line x1="349.4" y1="105" x2="359.4" y2="95"/></g><circle cx="432.5" cy="100" r="7" class="okc"/><g class="lost"><circle cx="510.6" cy="100" r="7"/><line x1="505.6" y1="95" x2="515.6" y2="105"/><line x1="505.6" y1="105" x2="515.6" y2="95"/></g><g class="lost"><circle cx="588.8" cy="100" r="7"/><line x1="583.8" y1="95" x2="593.8" y2="105"/><line x1="583.8" y1="105" x2="593.8" y2="95"/></g><g class="lost"><circle cx="666.9" cy="100" r="7"/><line x1="661.9" y1="95" x2="671.9" y2="105"/><line x1="661.9" y1="105" x2="671.9" y2="95"/></g><g class="lost"><circle cx="745.0" cy="100" r="7"/><line x1="740.0" y1="95" x2="750.0" y2="105"/><line x1="740.0" y1="105" x2="750.0" y2="95"/></g><circle cx="823.1" cy="100" r="7" class="okc"/>
    <rect x="120.0" y="118" width="359.5" height="14" rx="4" class="loop"/><rect x="482.5" y="118" width="359.5" height="14" rx="4" class="loop"/><text x="301.2" y="129" class="lp" text-anchor="middle">c ≈ 2.9 ms</text><text x="663.8" y="129" class="lp" text-anchor="middle">c ≈ 2.9 ms</text>
  </g>
  <g v-click="2">
    <text x="0" y="175" class="rl">con FIFO</text>
    <circle cx="120.0" cy="170" r="7" class="okc"/><circle cx="198.1" cy="170" r="7" class="okc"/><circle cx="276.2" cy="170" r="7" class="okc"/><circle cx="354.4" cy="170" r="7" class="okc"/><circle cx="432.5" cy="170" r="7" class="okc"/><circle cx="510.6" cy="170" r="7" class="okc"/><circle cx="588.8" cy="170" r="7" class="okc"/><circle cx="666.9" cy="170" r="7" class="okc"/><circle cx="745.0" cy="170" r="7" class="smp dim"/><circle cx="823.1" cy="170" r="7" class="smp dim"/><path d="M112.0,186 v6 H674.9 v-6" class="brk"/><line x1="745.0" y1="150" x2="745.0" y2="196" class="rd"/><text x="751.0" y="152" class="rdl">lectura (cada 5 ms)</text>
  </g>
  <text x="120.0" y="222" class="ax" text-anchor="middle">0</text><text x="245.0" y="222" class="ax" text-anchor="middle">1</text><text x="370.0" y="222" class="ax" text-anchor="middle">2</text><text x="495.0" y="222" class="ax" text-anchor="middle">3</text><text x="620.0" y="222" class="ax" text-anchor="middle">4</text><text x="745.0" y="222" class="ax" text-anchor="middle">5</text><text x="870.0" y="222" class="ax" text-anchor="middle">6</text>
  <text x="0" y="222" class="ax">tiempo (ms)</text>
</svg>

<div class="tl-f">
<div>

$T = \tfrac{1}{f} = 0.625\ \text{ms}$

</div>
<div v-click="1">

$1600 \times 2.9\ \text{ms} = \textcolor{#ff7a7a}{4.6\ \text{s}}$
<div class="faint">de trabajo por cada segundo ✗ → solo 1 / 2.9 ms ≈ 345 muestras/s</div>

</div>
<div v-click="2">

$125\ \text{lecturas} \times 3\ \text{ms} \approx \textcolor{#3ddc97}{0.4\ \text{s}}$
<div class="faint">por segundo ✓ (~13 muestras por lectura) · FIFO 2 KB ≈ 180 ms de margen</div>

</div>
</div>

---

<div class="kicker">07 · La solución</div>

# `fifo_take`: <span class="accent">una lectura, varias muestras</span>

<div class="grid-code">
<div>
<div class="code-title">esp32/main/main.c · fifo_take (extracto simplificado)</div>

```c {2-4|6-8|10-17}
/* 1. ¿Cuántos bytes hay? */
uint8_t reg = REG_FIFO_LENGTH, len_buf[2];
device_read(s_dev, &reg, len_buf, 2, TAG);
size_t length = len_buf[0] | ((size_t)(len_buf[1] & 0x3F) << 8);

/* 2. Leerlos todos en una sola transferencia */
reg = REG_FIFO_DATA;
device_read(s_dev, &reg, s_fifo_buf, length, TAG);

/* 3. Separar los frames */
while (i < length) {
    uint8_t header = s_fifo_buf[i] & 0xFC;
    if (header == FRAME_ACC)       size = 6;  /* x, y, z  */
    else if (header == FRAME_SKIP) size = 1;  /* perdidas */
    /* ... */
    i += 1 + size;
}
```

</div>
<div class="fbuf">
  <div class="fb-len"><span class="muted">FIFO_LENGTH</span> <b>= 30 B</b></div>
  <div v-click="1">
    <div class="fb-t">s_fifo_buf · una sola lectura I²C</div>
    <div class="fr acc"><span class="hd">0x84</span><span class="by"></span><span class="by"></span><span class="by"></span><span class="by"></span><span class="by"></span><span class="by"></span><span class="fl" v-click="2">seq = n</span></div><div class="fr acc"><span class="hd">0x84</span><span class="by"></span><span class="by"></span><span class="by"></span><span class="by"></span><span class="by"></span><span class="by"></span><span class="fl" v-click="2">seq = n+1</span></div><div class="fr skip"><span class="hd">0x40</span><span class="by n3">03</span><span class="fl" v-click="2">skip 3 → seq += 3</span></div><div class="fr acc"><span class="hd">0x84</span><span class="by"></span><span class="by"></span><span class="by"></span><span class="by"></span><span class="by"></span><span class="by"></span><span class="fl" v-click="2">seq = n+5</span></div><div class="fr acc"><span class="hd">0x84</span><span class="by"></span><span class="by"></span><span class="by"></span><span class="by"></span><span class="by"></span><span class="by"></span><span class="fl" v-click="2">seq = n+6</span></div>
  </div>
  <div class="fb-key" v-click="2"><div><span class="hd">0x84</span> muestra: encabezado + 6 B (x, y, z)</div><div><span class="hd sk">0x40</span> skip: el sensor perdió n muestras</div></div>
</div>
</div>

---

<div class="kicker">08 · Tiempos</div>

# `t_us` es estimado: <span class="accent">la FIFO no guarda la hora</span>

<svg class="ts" viewBox="0 0 884 236">
  <text x="0" y="51" class="rl">real</text><text x="0" y="68" class="rs">(no la conocemos)</text>
  <circle cx="163.6" cy="46" r="7" class="tr"/><circle cx="237.3" cy="46" r="7" class="tr"/><circle cx="311.1" cy="46" r="7" class="tr"/><circle cx="384.9" cy="46" r="7" class="tr"/><circle cx="458.6" cy="46" r="7" class="tr"/><circle cx="532.4" cy="46" r="7" class="tr"/><circle cx="606.1" cy="46" r="7" class="tr"/><circle cx="679.9" cy="46" r="7" class="tr"/><circle cx="753.6" cy="46" r="7" class="tr later"/><circle cx="827.4" cy="46" r="7" class="tr later"/>
  <line x1="730.0" y1="20" x2="730.0" y2="200" class="rd"/>
  <text x="722.0" y="14" class="rdl" text-anchor="end">lectura · t_read</text>
  <g v-click="1">
    <text x="0" y="131" class="rl">estimado</text>
    <circle cx="176.9" cy="126" r="7" class="es"/><circle cx="250.6" cy="126" r="7" class="es"/><circle cx="324.4" cy="126" r="7" class="es"/><circle cx="398.1" cy="126" r="7" class="es"/><circle cx="471.9" cy="126" r="7" class="es"/><circle cx="545.6" cy="126" r="7" class="es"/><circle cx="619.4" cy="126" r="7" class="es"/><circle cx="693.1" cy="126" r="7" class="es"/>
    <path d="M693.1,150 v8 H730.0 v-8" class="br"/>
    <text x="711.6" y="176" class="brl" text-anchor="middle">T/2</text>
    <path d="M176.9,150 v8 H250.6 v-8" class="br"/>
    <text x="213.8" y="176" class="brl" text-anchor="middle">T</text>
    <text x="398.1" y="176" class="brl2" text-anchor="middle">← hacia atrás, una cada T</text>
  </g>
  <text x="140.0" y="226" class="ax" text-anchor="middle">0</text><text x="258.0" y="226" class="ax" text-anchor="middle">1</text><text x="376.0" y="226" class="ax" text-anchor="middle">2</text><text x="494.0" y="226" class="ax" text-anchor="middle">3</text><text x="612.0" y="226" class="ax" text-anchor="middle">4</text><text x="730.0" y="226" class="ax" text-anchor="middle">5</text><text x="848.0" y="226" class="ax" text-anchor="middle">6</text>
  <text x="0" y="226" class="ax">tiempo (ms)</text>
</svg>

<div class="ts-f">
<div>

$t_{\text{nueva}} = t_{\text{read}} - \tfrac{\min(T,\,P)}{2}$
<div class="faint">en promedio, la más nueva tiene medio periodo de edad</div>

</div>
<div v-click="2">

$\text{paso} = T + \tfrac{\text{error}}{8\,(n + \text{skip})}$
<div class="faint">lecturas siguientes: corrige 1/8 del desvío · nunca retrocede</div>

</div>
<div v-click="3">

$\text{error} > 20\ \text{ms} \Rightarrow$ re-anclar
<div class="faint">tras un atraso grande (FIFO llena), vuelve al reloj de una vez</div>

</div>
</div>

---

<div class="kicker">Decisión 1 · Dos canales</div>

# Control confiable, <span class="accent">datos elegibles</span>

<svg class="ch2" viewBox="0 0 884 330">
  <defs>
    <marker id="m2" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#ffc24b"/></marker>
    <marker id="m3" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#b3c0d4"/></marker>
  </defs>
  <!-- extremos -->
  <rect x="0" y="8" width="118" height="140" rx="12" class="end"/>
  <text x="59" y="84" class="endt" text-anchor="middle">ESP32</text>
  <rect x="766" y="8" width="118" height="140" rx="12" class="end"/>
  <text x="825" y="84" class="endt" text-anchor="middle">Raspberry Pi</text>
  <!-- canal de control -->
  <rect x="128" y="22" width="628" height="46" rx="23" class="pipe"/>
  <text x="150" y="16" class="pl">control · TCP :10001</text>
  <g class="msgs">
    <rect x="198" y="31" width="104" height="28" rx="14" class="pill pi"/><text x="250" y="50" class="mt pi" text-anchor="middle">← CONFIG</text>
    <rect x="328" y="31" width="104" height="28" rx="14" class="pill esp"/><text x="380" y="50" class="mt esp" text-anchor="middle">ACK →</text>
    <rect x="458" y="31" width="104" height="28" rx="14" class="pill pi"/><text x="510" y="50" class="mt pi" text-anchor="middle">← STOP</text>
    <rect x="588" y="31" width="104" height="28" rx="14" class="pill esp"/><text x="640" y="50" class="mt esp" text-anchor="middle">END →</text>
  </g>
  <!-- canal de datos -->
  <rect x="128" y="90" width="628" height="46" rx="23" class="pipe data"/>
  <text x="150" y="160" class="pl">datos · TCP o UDP :10000 · solo de ida</text>
  <g>
    <rect x="160" y="103" width="22" height="20" rx="4" class="pk"/><rect x="190" y="103" width="22" height="20" rx="4" class="pk"/><rect x="220" y="103" width="22" height="20" rx="4" class="pk"/><rect x="250" y="103" width="22" height="20" rx="4" class="pk"/><rect x="280" y="103" width="22" height="20" rx="4" class="pk"/><rect x="310" y="103" width="22" height="20" rx="4" class="pk"/><rect x="340" y="103" width="22" height="20" rx="4" class="pk"/><rect x="370" y="103" width="22" height="20" rx="4" class="pk"/><rect x="400" y="103" width="22" height="20" rx="4" class="pk"/><rect x="430" y="103" width="22" height="20" rx="4" class="pk"/><rect x="460" y="103" width="22" height="20" rx="4" class="pk"/><rect x="490" y="103" width="22" height="20" rx="4" class="pk"/><rect x="520" y="103" width="22" height="20" rx="4" class="pk"/><rect x="550" y="103" width="22" height="20" rx="4" class="pk"/><rect x="580" y="103" width="22" height="20" rx="4" class="pk"/><rect x="610" y="103" width="22" height="20" rx="4" class="pk"/>
    <line x1="650" y1="113" x2="735" y2="113" class="ma data"/>
  </g>
  <!-- vida de cada conexión -->
  <g v-click>
    <text x="0" y="214" class="gl">control</text>
    <rect x="128" y="198" width="728" height="24" rx="6" class="gc"/>
    <text x="140" y="215" class="gt">abierta desde el arranque · espera CONFIG entre sesiones</text>
    <text x="0" y="262" class="gl">datos</text>
    <rect x="170" y="246" width="150" height="24" rx="6" class="gd"/><text x="245" y="263" class="gt2" text-anchor="middle">sesión 1 · TCP</text>
    <rect x="400" y="246" width="150" height="24" rx="6" class="gd"/><text x="475" y="263" class="gt2" text-anchor="middle">sesión 2 · UDP</text>
    <rect x="630" y="246" width="150" height="24" rx="6" class="gd"/><text x="705" y="263" class="gt2" text-anchor="middle">sesión 3 · TCP</text>
    <line x1="128" y1="296" x2="856" y2="296" class="tax" marker-end="url(#m3)"/>
    <text x="128" y="318" class="gl2">encendido</text><text x="856" y="318" class="gl2" text-anchor="end">tiempo</text>
  </g>
</svg>

<div class="ch2-foot" v-click>Control por UDP: <b>CONFIG perdido</b> = la sesión no empieza · <b>END perdido</b> = total desconocido</div>

---

<div class="kicker">GUI web · RF8</div>

# Un tercer canal: <span class="accent">la Pi y el navegador</span>

<svg class="gw" viewBox="0 0 884 300">
  <defs>
    <marker id="gy" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#ffc24b"/></marker>
    <marker id="gb" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#4cc3ff"/></marker>
  </defs>
  <!-- navegadores -->
  <rect x="0" y="55" width="128" height="70" rx="10" class="bx acc"/><text x="64" y="86" class="t" text-anchor="middle">Navegador</text><text x="64" y="104" class="ts" text-anchor="middle">EventSource</text>
  <rect x="0" y="160" width="128" height="70" rx="10" class="bx acc"/><text x="64" y="191" class="t" text-anchor="middle">Otro PC</text><text x="64" y="209" class="ts" text-anchor="middle">misma red</text>
  <!-- Pi -->
  <rect x="198" y="4" width="544" height="290" rx="14" class="grp"/>
  <text x="216" y="28" class="t">Raspberry Pi · <tspan class="tsm">web_server.py</tspan></text>
  <rect x="216" y="48" width="118" height="196" rx="9" class="bx"/>
  <text x="275" y="140" class="t" text-anchor="middle">Hilos HTTP</text><text x="275" y="158" class="ts" text-anchor="middle">1 por página</text><text x="275" y="174" class="tsm" text-anchor="middle">:8080</text>
  <rect x="372" y="128" width="140" height="116" rx="9" class="bx"/>
  <text x="442" y="152" class="t" text-anchor="middle">Hub</text>
  <g class="q"><rect x="392" y="166" width="100" height="16" rx="3"/><rect x="392" y="190" width="100" height="16" rx="3"/></g>
  <text x="442" y="178" class="tq" text-anchor="middle">cola · página 1</text><text x="442" y="202" class="tq" text-anchor="middle">cola · página 2</text>
  <text x="442" y="230" class="ts" text-anchor="middle">máx. 500 · lock</text>
  <rect x="558" y="48" width="166" height="196" rx="9" class="bx"/>
  <text x="641" y="70" class="t" text-anchor="middle">Hilo de adquisición</text>
  <rect x="572" y="82" width="138" height="24" rx="5" class="sb"/><text x="641" y="99" class="tsm" text-anchor="middle">sockets :10001 · :10000</text>
  <rect x="572" y="114" width="138" height="24" rx="5" class="sb"/><text x="641" y="131" class="tsm" text-anchor="middle">SampleTracker</text>
  <rect x="572" y="146" width="138" height="24" rx="5" class="sb"/><text x="641" y="163" class="tsm" text-anchor="middle">CSV + JSON</text>
  <rect x="572" y="196" width="138" height="36" rx="5" class="sb hi"/><text x="641" y="213" class="tsm" text-anchor="middle">LiveFeed</text><text x="641" y="227" class="tq" text-anchor="middle">lote cada 0.1 s</text>
  <!-- ESP32 -->
  <rect x="778" y="95" width="106" height="110" rx="10" class="bx acc"/><text x="831" y="155" class="t" text-anchor="middle">ESP32</text>
  <!-- comandos -->
  <g v-click="1">
    <line x1="130" y1="72" x2="213" y2="72" class="ay" marker-end="url(#gy)"/>
    <text x="172" y="63" class="ly" text-anchor="middle">POST /start</text>
    <line x1="213" y1="108" x2="132" y2="108" class="ay dash" marker-end="url(#gy)"/>
    <text x="172" y="100" class="ly2" text-anchor="middle">200 · 409</text>
    <line x1="336" y1="72" x2="554" y2="72" class="ay" marker-end="url(#gy)"/>
    <text x="445" y="63" class="ly" text-anchor="middle">request_start(config)</text>
    <line x1="726" y1="118" x2="774" y2="118" class="ay" marker-end="url(#gy)"/>
    <text x="750" y="110" class="ly" text-anchor="middle">CONFIG</text>
  </g>
  <!-- datos -->
  <g v-click="2">
    <line x1="776" y1="180" x2="728" y2="180" class="ab" marker-end="url(#gb)"/>
    <text x="752" y="198" class="lb" text-anchor="middle">datos</text>
    <line x1="570" y1="214" x2="516" y2="214" class="ab" marker-end="url(#gb)"/>
    <line x1="370" y1="186" x2="338" y2="186" class="ab" marker-end="url(#gb)"/>
    <line x1="213" y1="196" x2="132" y2="196" class="ab" marker-end="url(#gb)"/>
    <line x1="213" y1="196" x2="132" y2="124" class="ab" marker-end="url(#gb)"/>
    <text x="172" y="222" class="lb" text-anchor="middle">SSE /events</text>
    <text x="440" y="270" class="lb2" text-anchor="middle">≈ 10 eventos/s con ~160 puntos cada uno · no 1600 mensajes/s</text>
  </g>
</svg>

<div class="gw-chips" v-click="3">
  <span><b>SSE</b> · solo Pi → página, reconexión automática</span>
  <span><b>1 cola por página</b> · ninguna frena la adquisición</span>
  <span><b>Validación ×3</b> · página → Pi → ESP32</span>
</div>

---

<div class="kicker">Decisión 2 · Modos de lectura</div>

# Secuencial vs paralelo: <span class="accent">¿quién espera a quién?</span>

<svg class="md" viewBox="0 0 884 262">
  <text x="0" y="30" class="rl">Secuencial</text>
  <text x="0" y="56" class="rs">1 tarea · core 0</text>
  <rect x="175.0" y="40" width="17.2" height="22" rx="4" class="rd"/><rect x="192.2" y="40" width="25.8" height="22" rx="4" class="sd"/><rect x="218.0" y="40" width="107.5" height="22" rx="4" class="wt"/><rect x="325.5" y="40" width="17.2" height="22" rx="4" class="rd"/><rect x="342.7" y="40" width="25.8" height="22" rx="4" class="sd"/><rect x="368.5" y="40" width="107.5" height="22" rx="4" class="wt"/><rect x="476.0" y="40" width="17.2" height="22" rx="4" class="rd"/><rect x="493.2" y="40" width="193.5" height="22" rx="4" class="sd slow"/><text x="590.0" y="56" class="bl" text-anchor="middle">envío lento</text><rect x="686.7" y="40" width="107.5" height="22" rx="4" class="wt"/><rect x="794.2" y="40" width="17.2" height="22" rx="4" class="rd"/><rect x="811.4" y="40" width="25.8" height="22" rx="4" class="sd"/><rect x="837.2" y="40" width="25.8" height="22" rx="4" class="wt"/>
  <text x="798.2" y="88" class="late" text-anchor="middle">la lectura se atrasa</text>
  <line x1="794.2" y1="66" x2="794.2" y2="76" class="lateln"/>
  <g v-click="1">
    <text x="0" y="132" class="rl">Paralelo</text>
    <text x="0" y="158" class="rs">read_task · core 1 · prio 5</text>
    <rect x="175.0" y="140" width="17.2" height="22" rx="4" class="rd"/><rect x="192.2" y="140" width="107.5" height="22" rx="4" class="wt"/><rect x="299.7" y="140" width="17.2" height="22" rx="4" class="rd"/><rect x="316.9" y="140" width="107.5" height="22" rx="4" class="wt"/><rect x="424.4" y="140" width="17.2" height="22" rx="4" class="rd"/><rect x="441.6" y="140" width="107.5" height="22" rx="4" class="wt"/><rect x="549.1" y="140" width="17.2" height="22" rx="4" class="rd"/><rect x="566.3" y="140" width="107.5" height="22" rx="4" class="wt"/><rect x="673.8" y="140" width="17.2" height="22" rx="4" class="rd"/><rect x="691.0" y="140" width="107.5" height="22" rx="4" class="wt"/><rect x="798.5" y="140" width="17.2" height="22" rx="4" class="rd"/><rect x="815.7" y="140" width="47.3" height="22" rx="4" class="wt"/>
    <line x1="192.2" y1="163" x2="192.2" y2="186" class="q"/><line x1="316.9" y1="163" x2="316.9" y2="186" class="q"/><line x1="441.6" y1="163" x2="441.6" y2="186" class="q"/><line x1="566.3" y1="163" x2="566.3" y2="186" class="q"/><line x1="691.0" y1="163" x2="691.0" y2="186" class="q"/><line x1="815.7" y1="163" x2="815.7" y2="186" class="q"/>
    <text x="0" y="204" class="rs">envío · core 0</text>
    <rect x="192.2" y="188" width="25.8" height="22" rx="4" class="sd"/><rect x="316.9" y="188" width="25.8" height="22" rx="4" class="sd"/><rect x="441.6" y="188" width="193.5" height="22" rx="4" class="sd slow"/><text x="538.3" y="204" class="bl" text-anchor="middle">envío lento</text><rect x="635.1" y="188" width="38.7" height="22" rx="4" class="sd"/><rect x="691.0" y="188" width="25.8" height="22" rx="4" class="sd"/><rect x="815.7" y="188" width="25.8" height="22" rx="4" class="sd"/>
    <text x="572.3" y="180" class="qt">cola (512)</text>
  </g>
  <text x="175.0" y="250" class="ax" text-anchor="middle">0</text><text x="282.5" y="250" class="ax" text-anchor="middle">5</text><text x="390.0" y="250" class="ax" text-anchor="middle">10</text><text x="497.5" y="250" class="ax" text-anchor="middle">15</text><text x="605.0" y="250" class="ax" text-anchor="middle">20</text><text x="712.5" y="250" class="ax" text-anchor="middle">25</text><text x="820.0" y="250" class="ax" text-anchor="middle">30</text>
  <text x="0" y="250" class="ax">ms (ilustrativo)</text>
</svg>

<div class="md-legend">
  <span><i class="sw rd"></i>leer FIFO</span><span><i class="sw sd"></i>enviar</span><span><i class="sw wt"></i>esperar 5 ms</span>
</div>

<div class="md-cards" v-click="2">
  <div class="panel"><b>Secuencial</b> · simple; si el envío se atrasa, la <b>FIFO</b> guarda <span class="muted">(≈ 180 ms)</span></div>
  <div class="panel panel-ours"><b>Paralelo</b> · lectura regular; colchón <b>FIFO + cola</b> <span class="muted">(≈ 180 + 320 ms)</span></div>
  <div class="panel"><b>Medido</b> · ambos <b>0 %</b> de pérdida a 1600 Hz <span class="muted">(TCP y UDP)</span></div>
</div>

---

<div class="kicker">Decisión 3 · UDP por lotes</div>

# Menos datagramas, <span class="accent">más muestras en cada uno</span>

<div class="bt">
<div class="bt-l">
  <div class="bt-h">Antes · 1 muestra por datagrama</div>
  <div class="dgs"><div class="dg bad"><span class="h">28 B</span><span class="s"></span></div><div class="dg bad"><span class="h">28 B</span><span class="s"></span></div><div class="dg bad"><span class="h">28 B</span><span class="s"></span></div><div class="dg bad"><span class="h">28 B</span><span class="s"></span></div><span class="more">… 1617 /s</span></div>
  <div class="bt-n"><b class="bad">λ = 1617</b> datagramas/s pedidos · el ESP32 alcanza <b>μ ≈ 810</b></div>

  <div v-click="2">
  <div class="bt-h ok" style="margin-top:22px">Ahora · una lectura de FIFO = 1 datagrama</div>
  <div class="dgs"><div class="dg ok"><span class="h">28 B</span><span class="s"></span><span class="s"></span><span class="s"></span><span class="s"></span><span class="s"></span><span class="s"></span><span class="s"></span><span class="s"></span><span class="s"></span><span class="s"></span><span class="s"></span><span class="s"></span><span class="s"></span></div><span class="more">… ≈ 125 /s</span></div>
  <div class="bt-n">≈ 13 muestras/datagrama · máx. 100 = 1400 B &lt; MTU</div>
  </div>

  <div class="bt-f" v-click="1">

$1617 \times 1.2\ \text{ms} \approx \textcolor{#ff7a7a}{1.9\ \text{s}}$ ✗

<span v-click="2">$\phantom{1}125 \times 1.2\ \text{ms} \approx \textcolor{#3ddc97}{0.15\ \text{s}}$ ✓</span>
<div class="faint">trabajo por segundo · 1.2 ms = 1/810 por datagrama (medido)</div>

  </div>
</div>

<svg class="bt-c" viewBox="0 0 480 290">
  <text x="52" y="14" class="ct">Pérdida UDP a 1600 Hz</text>
  <line x1="52" y1="250.0" x2="462" y2="250.0" class="gl"/><text x="44" y="254.0" class="ax" text-anchor="end">0%</text><line x1="52" y1="211.0" x2="462" y2="211.0" class="gl"/><text x="44" y="215.0" class="ax" text-anchor="end">10%</text><line x1="52" y1="172.0" x2="462" y2="172.0" class="gl"/><text x="44" y="176.0" class="ax" text-anchor="end">20%</text><line x1="52" y1="133.0" x2="462" y2="133.0" class="gl"/><text x="44" y="137.0" class="ax" text-anchor="end">30%</text><line x1="52" y1="94.0" x2="462" y2="94.0" class="gl"/><text x="44" y="98.0" class="ax" text-anchor="end">40%</text><line x1="52" y1="55.0" x2="462" y2="55.0" class="gl"/><text x="44" y="59.0" class="ax" text-anchor="end">50%</text>
  <text x="72.5" y="268" class="ax" text-anchor="middle">1</text><text x="93.0" y="268" class="ax" text-anchor="middle">2</text><text x="113.5" y="268" class="ax" text-anchor="middle">3</text><text x="154.5" y="268" class="ax" text-anchor="middle">5</text><text x="257.0" y="268" class="ax" text-anchor="middle">10</text><text x="462.0" y="268" class="ax" text-anchor="middle">20</text>
  <text x="257" y="286" class="ax" text-anchor="middle">duración de la sesión (s)</text>
  <g v-click="1">
    <line x1="52" y1="55.4" x2="462" y2="55.4" class="asy"/>
    <path d="M72.5,186.1 L77.6,159.9 L82.8,142.5 L87.9,130.1 L93.0,120.7 L98.1,113.5 L103.2,107.7 L108.4,102.9 L113.5,98.9 L118.6,95.6 L123.8,92.7 L128.9,90.2 L134.0,88.0 L139.1,86.1 L144.2,84.4 L149.4,82.9 L154.5,81.5 L159.6,80.3 L164.8,79.1 L169.9,78.1 L175.0,77.1 L180.1,76.3 L185.2,75.5 L190.4,74.7 L195.5,74.0 L200.6,73.4 L205.8,72.8 L210.9,72.2 L216.0,71.7 L221.1,71.2 L226.2,70.7 L231.4,70.3 L236.5,69.9 L241.6,69.5 L246.8,69.1 L251.9,68.8 L257.0,68.4 L262.1,68.1 L267.2,67.8 L272.4,67.5 L277.5,67.2 L282.6,67.0 L287.8,66.7 L292.9,66.5 L298.0,66.3 L303.1,66.0 L308.2,65.8 L313.4,65.6 L318.5,65.4 L323.6,65.2 L328.8,65.0 L333.9,64.9 L339.0,64.7 L344.1,64.5 L349.2,64.4 L354.4,64.2 L359.5,64.1 L364.6,63.9 L369.8,63.8 L374.9,63.7 L380.0,63.5 L385.1,63.4 L390.2,63.3 L395.4,63.2 L400.5,63.1 L405.6,62.9 L410.8,62.8 L415.9,62.7 L421.0,62.6 L426.1,62.5 L431.2,62.4 L436.4,62.3 L441.5,62.2 L446.6,62.2 L451.8,62.1 L456.9,62.0 L462.0,61.9" class="model"/>
    <circle cx="72.5" cy="181.0" r="5.5" class="pr"/><circle cx="93.0" cy="119.0" r="5.5" class="pr"/><circle cx="113.5" cy="101.0" r="5.5" class="pr"/><circle cx="154.5" cy="81.9" r="5.5" class="pr"/><circle cx="257.0" cy="68.3" r="5.5" class="pr"/><circle cx="462.0" cy="62.0" r="5.5" class="pr"/>
    <text x="460" y="47.4" class="lbl r" text-anchor="end">1 − μ/λ</text>
    <text x="134.0" y="164.2" class="lbl r">medido (antes)</text>
    <text x="134.0" y="187.6" class="lbl m">modelo: 1 − (μT + Q)/(λT)</text>
  </g>
  <g v-click="2">
    <circle cx="249.0" cy="250.0" r="5.5" class="pg"/><circle cx="253.0" cy="250.0" r="5.5" class="pg"/><circle cx="257.0" cy="250.0" r="5.5" class="pg"/><circle cx="261.0" cy="250.0" r="5.5" class="pg"/><circle cx="265.0" cy="250.0" r="5.5" class="pg"/>
    <text x="273.0" y="240.0" class="lbl g">por lotes: 0 % (7 sesiones de 10 s)</text>
  </g>
</svg>
</div>

---

<div class="kicker">Resultados · 1600 Hz · sesiones de 10 s</div>

# Con el diseño final, <span class="accent">TCP y UDP rinden igual</span>

<div class="rs-tiles">
  <div class="panel"><div class="stat ok"><span class="stat-value">0 %</span><span class="stat-label">pérdida · TCP y UDP · 10 sesiones</span></div></div>
  <div class="panel"><div class="stat"><span class="stat-value">1617<small>/s</small></span><span class="stat-label">tasa real del sensor (pedido 1600)</span></div></div>
  <div class="panel"><div class="stat ok"><span class="stat-value">&lt; 10<small>ms</small></span><span class="stat-label">retraso acumulado · <span class="nw">UDP antes: <b class="bad-t">0.65 s</b></span></span></div></div>
</div>

<div class="rs-charts">
<svg viewBox="0 0 430 140" v-click="1">
  <text x="70" y="12" class="ct">Jitter J (RFC 3550) por sesión · ms</text>
  <line x1="70.0" y1="22" x2="70.0" y2="112" class="gl"/><text x="70.0" y="130" class="ax" text-anchor="middle">0</text><line x1="150.0" y1="22" x2="150.0" y2="112" class="gl"/><text x="150.0" y="130" class="ax" text-anchor="middle">1</text><line x1="230.0" y1="22" x2="230.0" y2="112" class="gl"/><text x="230.0" y="130" class="ax" text-anchor="middle">2</text><line x1="310.0" y1="22" x2="310.0" y2="112" class="gl"/><text x="310.0" y="130" class="ax" text-anchor="middle">3</text><line x1="390.0" y1="22" x2="390.0" y2="112" class="gl"/><text x="390.0" y="130" class="ax" text-anchor="middle">4</text>
  <text x="0" y="58" class="rl">TCP</text><text x="0" y="98" class="rl">UDP</text>
  <circle cx="201.2" cy="54.0" r="5.5" class="pt"/><circle cx="264.4" cy="54.0" r="5.5" class="pt"/><circle cx="356.4" cy="54.0" r="5.5" class="pt"/>
  <circle cx="155.6" cy="94.0" r="5.5" class="pu"/><circle cx="193.2" cy="94.0" r="5.5" class="pu"/><circle cx="237.2" cy="94.0" r="5.5" class="pu"/><circle cx="274.0" cy="94.0" r="5.5" class="pu"/><circle cx="210.0" cy="94.0" r="5.5" class="pu"/><circle cx="298.8" cy="94.0" r="5.5" class="pu"/><circle cx="185.2" cy="94.0" r="5.5" class="pu"/>
</svg>
<svg viewBox="0 0 430 140" v-click="2">
  <text x="70" y="12" class="ct">Muestras duplicadas por sesión</text>
  <line x1="70.0" y1="22" x2="70.0" y2="112" class="gl"/><text x="70.0" y="130" class="ax" text-anchor="middle">0</text><line x1="219.5" y1="22" x2="219.5" y2="112" class="gl"/><text x="219.5" y="130" class="ax" text-anchor="middle">13</text><line x1="369.0" y1="22" x2="369.0" y2="112" class="gl"/><text x="369.0" y="130" class="ax" text-anchor="middle">26</text>
  <text x="0" y="58" class="rl">TCP</text><text x="0" y="98" class="rl">UDP</text>
  <circle cx="70.0" cy="54.0" r="5.5" class="pt"/><circle cx="70.0" cy="45.0" r="5.5" class="pt"/><circle cx="70.0" cy="36.0" r="5.5" class="pt"/>
  <circle cx="219.5" cy="94.0" r="5.5" class="pu"/><circle cx="242.5" cy="94.0" r="5.5" class="pu"/><circle cx="219.5" cy="85.0" r="5.5" class="pu"/><circle cx="369.0" cy="94.0" r="5.5" class="pu"/><circle cx="219.5" cy="76.0" r="5.5" class="pu"/><circle cx="231.0" cy="94.0" r="5.5" class="pu"/><circle cx="242.5" cy="85.0" r="5.5" class="pu"/>
  <text x="259.8" y="74" class="nt">≈ 1 datagrama repetido</text>
</svg>
</div>

<div class="rs-foot" v-click="3">Lo que queda distinto son las <b>garantías</b> · TCP: todo, una vez, en orden · UDP: lo verifica <code>SampleTracker</code></div>

---

<div class="kicker">Datos · rango y frecuencia</div>

# Rango: <span class="accent">resolución</span> · Frecuencia: <span class="accent">ruido</span>

<div class="rf">
<div class="panel">
  <div class="panel-head">Rango (RF7) · la misma gravedad, 1 g</div>
  <div class="rg-head"><span></span><span>cuentas crudas por g</span><span></span><span>1 LSB</span></div>
  <div class="rg-row"><span class="rg-l">±2 g</span><div class="rg-tr"><div class="rg-bar" style="width:235px"></div><span class="rg-dot" style="left:233px"></span></div><span class="rg-v">16384</span><span class="rg-res">0.6 mm/s²</span></div><div class="rg-row"><span class="rg-l">±4 g</span><div class="rg-tr"><div class="rg-bar" style="width:117px"></div><span class="rg-dot" style="left:112px"></span></div><span class="rg-v">8192</span><span class="rg-res">1.2 mm/s²</span></div><div class="rg-row"><span class="rg-l">±8 g</span><div class="rg-tr"><div class="rg-bar" style="width:58px"></div><span class="rg-dot" style="left:56px"></span></div><span class="rg-v">4096</span><span class="rg-res">2.4 mm/s²</span></div><div class="rg-row"><span class="rg-l">±16 g</span><div class="rg-tr"><div class="rg-bar" style="width:29px"></div><span class="rg-dot" style="left:28px"></span></div><span class="rg-v">2048</span><span class="rg-res">4.8 mm/s²</span></div>
  <div class="rg-key"><span class="k bar"></span>teoría <span class="k dot"></span>promedio medido</div>
  <div class="rf-f" v-click="1">

$\text{escala} = \dfrac{\text{rango} \cdot 9.80665}{32768}\ \tfrac{\text{m/s}^2}{\text{LSB}}$
<div class="faint">más rango → no satura con golpes, pero cada cuenta vale más</div>

  </div>
</div>
<div class="panel" v-click="2">
  <div class="panel-head">Frecuencia · ruido en reposo, ±16 g</div>
  <div class="nz">
    <div class="nz-c"><div class="nz-b" style="height:54px"></div><b>4.5 LSB</b><span>400 Hz</span><small>21 mm/s²</small></div>
    <div class="nz-x">× 2</div>
    <div class="nz-c"><div class="nz-b hi" style="height:108px"></div><b>≈ 9 LSB</b><span>1600 Hz</span><small>≈ 43 mm/s²</small></div>
  </div>
  <div class="rf-f">

$\sigma \propto \sqrt{f} \;\Rightarrow\; \sqrt{1600/400} = 2$
<div class="faint">el filtro deja pasar una banda ∝ f · más frecuencia → ve vibraciones más rápidas (hasta f/2), con más ruido</div>

  </div>
</div>
</div>
