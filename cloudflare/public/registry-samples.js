/**
 * Registry sample previews — color swatches and procedural sound playback.
 * Pure sound primitives: silence, rumble, tone, hiss (REGISTRY_FOUNDATION).
 */
(function (global) {
  const SAMPLE_SEC = 1.2;
  const PRIMITIVES = ['silence', 'rumble', 'hum', 'tone', 'hiss', 'rustle', 'thump', 'click', 'whoosh', 'drip'];
  const PRIMITIVE_FREQ = {
    rumble: 65, hum: 120, tone: 330, hiss: 1400,
    thump: 80, click: 1800, drip: 520, whoosh: 900, rustle: 700,
  };
  const PRIMITIVE_DESC = {
    silence: 'No audible content',
    rumble: 'Low continuous — traffic, thunder, engines',
    hum: 'Steady drone — AC, fridge, electrical hum',
    tone: 'Clear mid pitch — alerts, whistles, voice',
    hiss: 'Sustained high — rain, spray, ventilation',
    rustle: 'Textured friction — leaves, crowd, gravel',
    thump: 'Low impact — footsteps, doors',
    click: 'Sharp transient — switch, tap, keyboard',
    whoosh: 'Sweeping air — wind gust, pass-by',
    drip: 'Sparse taps — water drip, tick',
  };
  let audioCtx = null;

  function getAudioContext() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    return audioCtx;
  }

  function escapeHtml(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  function clamp255(n) {
    return Math.max(0, Math.min(255, Math.round(Number(n) || 0)));
  }

  function resolveRgb(entry, primaries) {
    if (!entry) return null;
    if (entry.r != null && entry.g != null && entry.b != null) {
      return { r: clamp255(entry.r), g: clamp255(entry.g), b: clamp255(entry.b) };
    }
    const key = String(entry.key || '');
    const base = key.indexOf('_') > 0 ? key.slice(0, key.indexOf('_')) : key;
    const parts = base.split(',');
    if (parts.length >= 3) {
      const r = parseFloat(parts[0]);
      const g = parseFloat(parts[1]);
      const b = parseFloat(parts[2]);
      if (!Number.isNaN(r) && !Number.isNaN(g) && !Number.isNaN(b)) {
        return { r: clamp255(r), g: clamp255(g), b: clamp255(b) };
      }
    }
    const name = String(entry.name || '').replace(/\s*\(\d+,\d+,\d+\)\s*$/, '').trim().toLowerCase();
    if (name && Array.isArray(primaries)) {
      const p = primaries.find((x) => String(x.name || '').toLowerCase() === name);
      if (p) return { r: clamp255(p.r), g: clamp255(p.g), b: clamp255(p.b) };
    }
    return null;
  }

  function rgbCss(rgb) {
    if (!rgb) return 'transparent';
    return `rgb(${rgb.r}, ${rgb.g}, ${rgb.b})`;
  }

  function colorSwatchHtml(rgb, opts) {
    if (!rgb) return '<span class="registry-swatch registry-swatch--empty" title="No RGB">—</span>';
    const size = (opts && opts.large) ? 'registry-swatch-lg' : 'registry-swatch';
    const title = `${rgb.r}, ${rgb.g}, ${rgb.b}`;
    return `<span class="${size}" style="background:${rgbCss(rgb)}" title="${escapeHtml(title)}" role="img" aria-label="Color ${escapeHtml(title)}"></span>`;
  }

  function colorSwatchCell(entry, primaries) {
    const rgb = resolveRgb(entry, primaries);
    const label = rgb ? `rgb(${rgb.r},${rgb.g},${rgb.b})` : '—';
    return { html: `<span class="registry-sample-cell">${colorSwatchHtml(rgb)}<span class="registry-sample-label">${escapeHtml(label)}</span></span>` };
  }

  function schedulePrimitive(ctx, primitive, gainVal, duration, dest) {
    const t0 = ctx.currentTime;
    const t1 = t0 + duration;
    const g = ctx.createGain();
    g.gain.setValueAtTime(Math.max(0.001, gainVal), t0);
    g.gain.exponentialRampToValueAtTime(0.001, t1);
    g.connect(dest);

    if (primitive === 'silence') return;

    if (primitive === 'hiss' || primitive === 'rustle' || primitive === 'whoosh') {
      const len = Math.floor(ctx.sampleRate * duration);
      const buf = ctx.createBuffer(1, len, ctx.sampleRate);
      const ch = buf.getChannelData(0);
      for (let i = 0; i < len; i++) ch[i] = Math.random() * 2 - 1;
      const src = ctx.createBufferSource();
      src.buffer = buf;
      const filter = ctx.createBiquadFilter();
      if (primitive === 'hiss') {
        filter.type = 'highpass';
        filter.frequency.value = 900;
      } else if (primitive === 'whoosh') {
        filter.type = 'bandpass';
        filter.frequency.setValueAtTime(400, t0);
        filter.frequency.exponentialRampToValueAtTime(2200, t1);
        filter.Q.value = 0.8;
      } else {
        filter.type = 'bandpass';
        filter.frequency.value = 700;
        filter.Q.value = 0.5;
      }
      src.connect(filter);
      filter.connect(g);
      src.start(t0);
      src.stop(t1);
      return;
    }

    if (primitive === 'click') {
      const len = Math.floor(ctx.sampleRate * 0.04);
      const buf = ctx.createBuffer(1, len, ctx.sampleRate);
      const ch = buf.getChannelData(0);
      for (let i = 0; i < len; i++) ch[i] = (Math.random() * 2 - 1) * (1 - i / len);
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.connect(g);
      src.start(t0);
      return;
    }

    if (primitive === 'drip') {
      for (let i = 0; i < 3; i++) {
        const start = t0 + i * 0.28;
        const osc = ctx.createOscillator();
        const dg = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = PRIMITIVE_FREQ.drip;
        dg.gain.setValueAtTime(gainVal * 0.6, start);
        dg.gain.exponentialRampToValueAtTime(0.001, start + 0.08);
        osc.connect(dg);
        dg.connect(dest);
        osc.start(start);
        osc.stop(start + 0.09);
      }
      return;
    }

    if (primitive === 'thump') {
      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(120, t0);
      osc.frequency.exponentialRampToValueAtTime(50, t0 + 0.15);
      const tg = ctx.createGain();
      tg.gain.setValueAtTime(gainVal, t0);
      tg.gain.exponentialRampToValueAtTime(0.001, t0 + 0.2);
      osc.connect(tg);
      tg.connect(dest);
      osc.start(t0);
      osc.stop(t0 + 0.22);
      return;
    }

    const osc = ctx.createOscillator();
    osc.type = 'sine';
    osc.frequency.value = PRIMITIVE_FREQ[primitive] || 220;
    osc.connect(g);
    osc.start(t0);
    osc.stop(t1);
  }

  function playPrimitiveSound(primitive, strength) {
    if (primitive === 'silence') return;
    const ctx = getAudioContext();
    const master = ctx.createGain();
    const amp = Math.min(1, Math.max(0.08, Number(strength) <= 1 ? Number(strength) : Number(strength) / 100));
    master.gain.value = 0.35 * amp;
    master.connect(ctx.destination);
    schedulePrimitive(ctx, primitive, 1, SAMPLE_SEC, master);
  }

  function noisesFromDepth(depth) {
    if (!depth || typeof depth !== 'object') return [];
    const oc = depth.origin_noises;
    if (oc && typeof oc === 'object') {
      return Object.entries(oc).filter(([, v]) => Number(v) > 0);
    }
    return Object.entries(depth).filter(([k, v]) => PRIMITIVES.includes(k) && Number(v) > 0);
  }

  function playSoundBlend(depthBreakdown, strengthPct) {
    const ctx = getAudioContext();
    const master = ctx.createGain();
    const amp = Math.min(1, Math.max(0.08, Number(strengthPct) <= 1 ? Number(strengthPct) : Number(strengthPct) / 100));
    master.gain.value = 0.35 * amp;
    master.connect(ctx.destination);

    const entries = noisesFromDepth(depthBreakdown);
    if (!entries.length) {
      playPrimitiveSound('tone', amp);
      return;
    }
    const total = entries.reduce((s, [, v]) => s + Number(v), 0) || 1;
    entries.forEach(([primitive, weight]) => {
      const w = Number(weight) / total;
      if (w > 0.02 && primitive !== 'silence') {
        schedulePrimitive(ctx, primitive, w, SAMPLE_SEC, master);
      }
    });
  }

  function soundPlayButtonHtml(primitive, label) {
    const p = primitive || 'tone';
    const lbl = label || p;
    if (p === 'silence') {
      return `<span class="registry-sound-silent" title="Silence">Silent</span>`;
    }
    return `<button type="button" class="registry-sound-play" data-sound-primitive="${escapeHtml(p)}" aria-label="Play ${escapeHtml(lbl)} sample">▶</button>`;
  }

  function soundPlayCell(entry) {
    const depth = entry.depth_breakdown;
    const entries = noisesFromDepth(depth);
    let dominant = 'tone';
    if (entries.length) {
      entries.sort((a, b) => Number(b[1]) - Number(a[1]));
      dominant = entries[0][0];
    }
    const strength = entry.strength_pct != null ? entry.strength_pct : 0.5;
    const label = entry.name || dominant;
    if (dominant === 'silence' && entries.length <= 1) {
      return { html: `<span class="registry-sample-cell">${soundPlayButtonHtml('silence', label)}</span>` };
    }
    if (entries.length) {
      return {
        html: `<span class="registry-sample-cell"><button type="button" class="registry-sound-play" data-sound-blend="1" data-sound-strength="${escapeHtml(String(strength))}" data-sound-depth="${escapeHtml(JSON.stringify(depth || {}))}" aria-label="Play ${escapeHtml(label)} sample">▶</button></span>`,
      };
    }
    return {
      html: `<span class="registry-sample-cell"><button type="button" class="registry-sound-play" data-sound-primitive="${escapeHtml(dominant)}" data-sound-strength="${escapeHtml(String(strength))}" aria-label="Play ${escapeHtml(label)} sample">▶</button></span>`,
    };
  }

  function colorPrimaryCard(p) {
    const rgb = { r: clamp255(p.r), g: clamp255(p.g), b: clamp255(p.b) };
    return `<div class="registry-color-card">
      ${colorSwatchHtml(rgb, { large: true })}
      <span class="registry-color-name">${escapeHtml(p.name)}</span>
      <span class="registry-color-rgb">${rgb.r}, ${rgb.g}, ${rgb.b}</span>
    </div>`;
  }

  function soundPrimaryCard(primitive) {
    const label = primitive.charAt(0).toUpperCase() + primitive.slice(1);
    const desc = PRIMITIVE_DESC[primitive] || '';
    return `<div class="registry-sound-card">
      <span class="registry-sound-name">${escapeHtml(label)}</span>
      <span class="registry-sound-desc">${escapeHtml(desc)}</span>
      ${soundPlayButtonHtml(primitive, label)}
    </div>`;
  }

  function bindSoundButtons(root) {
    if (!root) return;
    root.addEventListener('click', (e) => {
      const btn = e.target.closest('.registry-sound-play');
      if (!btn) return;
      e.preventDefault();
      const blend = btn.getAttribute('data-sound-blend');
      const strength = parseFloat(btn.getAttribute('data-sound-strength') || '0.5');
      if (blend) {
        try {
          const depth = JSON.parse(btn.getAttribute('data-sound-depth') || '{}');
          playSoundBlend(depth, strength);
        } catch {
          playPrimitiveSound(btn.getAttribute('data-sound-primitive') || 'tone', strength);
        }
      } else {
        playPrimitiveSound(btn.getAttribute('data-sound-primitive') || 'tone', strength);
      }
    });
  }

  global.RegistrySamples = {
    resolveRgb,
    colorSwatchHtml,
    colorSwatchCell,
    colorPrimaryCard,
    soundPrimaryCard,
    soundPlayButtonHtml,
    soundPlayCell,
    bindSoundButtons,
    playPrimitiveSound,
    playSoundBlend,
    PRIMITIVES,
  };
})(typeof window !== 'undefined' ? window : globalThis);
