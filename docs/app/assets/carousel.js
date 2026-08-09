/* Caruselul de capturi — fizică, nu tranziții.
 *
 * Regula de la care pleacă tot: mișcarea începe din valoarea de pe ecran ACUM,
 * moștenește viteza degetului, proiectează momentul înainte și poate fi
 * apucată și inversată în orice clipă. De aceea nu există aici nicio
 * tranziție CSS și niciun keyframe pe poziție: ele nu pot fi prinse din zbor.
 */

(function () {
  'use strict';

  var root = document.querySelector('[data-carousel]');
  if (!root) return;

  var track = root.querySelector('.shots-track');
  var slides = Array.prototype.slice.call(track.children);
  var dots = Array.prototype.slice.call(root.querySelectorAll('.dot'));
  var caption = root.querySelector('.shot-caption');
  if (!slides.length) return;

  // Mișcare redusă: renunțăm complet la fizică și lăsăm derularea nativă,
  // cu scroll-snap din CSS. Nu e o versiune ciuntită — e alt mijloc pentru
  // același scop.
  var reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (reduced.matches) {
    bindDotsToScroll();
    return;
  }

  /* ── Arcul ───────────────────────────────────────────────────────────────
   * Parametrizarea lui Apple: raport de amortizare + „response" (cât de
   * repede ajunge la țintă, în secunde) — nu masă/rigiditate/amortizare.
   * damping 1.0 = fără depășire; sub 1.0 = depășește și oscilează.
   * Nu are durată fixă: timpul de așezare iese din parametri.
   */
  function Spring(damping, response) {
    this.zeta = damping;
    this.omega = (2 * Math.PI) / response;
    this.value = 0;
    this.velocity = 0;
    this.target = 0;
  }

  Spring.prototype.step = function (dt) {
    // Pas mic și fix: un dt mare (filă în fundal) ar face integrarea să explodeze.
    var h = Math.min(dt, 1 / 60);
    var k = this.omega * this.omega;
    var c = 2 * this.zeta * this.omega;
    var a = -k * (this.value - this.target) - c * this.velocity;
    this.velocity += a * h;
    this.value += this.velocity * h;
    return Math.abs(this.value - this.target) < 0.35 && Math.abs(this.velocity) < 12;
  };

  var spring = new Spring(1, 0.4);
  var raf = null;
  var lastFrame = 0;

  function tick(now) {
    var dt = lastFrame ? (now - lastFrame) / 1000 : 1 / 60;
    lastFrame = now;
    var settled = spring.step(dt);
    paint(spring.value);
    if (settled) {
      spring.value = spring.target;
      spring.velocity = 0;
      paint(spring.value);
      raf = null;
      lastFrame = 0;
      track.style.willChange = 'auto';
      return;
    }
    raf = requestAnimationFrame(tick);
  }

  function run() {
    if (raf) return;
    track.style.willChange = 'transform';
    lastFrame = 0;
    raf = requestAnimationFrame(tick);
  }

  function stop() {
    if (raf) cancelAnimationFrame(raf);
    raf = null;
    lastFrame = 0;
  }

  function paint(x) {
    track.style.transform = 'translate3d(' + x + 'px, 0, 0)';
  }

  /* ── Geometrie ─────────────────────────────────────────────────────────── */

  var index = 0;

  function slideStep() {
    if (slides.length < 2) return slides[0].offsetWidth;
    return slides[1].offsetLeft - slides[0].offsetLeft;
  }

  // Poziția care aduce cartea `i` în centrul zonei vizibile.
  function offsetFor(i) {
    var s = slides[i];
    if (!s) return 0;
    return root.clientWidth / 2 - (s.offsetLeft + s.offsetWidth / 2);
  }

  function minOffset() { return offsetFor(slides.length - 1); }
  function maxOffset() { return offsetFor(0); }

  function nearestIndex(x) {
    var best = 0;
    var bestDist = Infinity;
    for (var i = 0; i < slides.length; i++) {
      var d = Math.abs(x - offsetFor(i));
      if (d < bestDist) { bestDist = d; best = i; }
    }
    return best;
  }

  /* ── Proiecția momentului ────────────────────────────────────────────────
   * Nu sărim la cartea cea mai apropiată de punctul de ELIBERARE, ci la cea
   * mai apropiată de locul unde gestul se DUCE. Asta face ca o azvârlire
   * scurtă să arunce caruselul mai departe — „input mic, ieșire mare".
   * Formula e cea din codul de exemplu Apple (decădere exponențială),
   * nu v²/(2a) din manual.
   */
  function project(velocity, decelerationRate) {
    var d = decelerationRate === undefined ? 0.998 : decelerationRate;
    return (velocity / 1000) * d / (1 - d);
  }

  /* ── Rezistență la capete ────────────────────────────────────────────────
   * La margine nu ne oprim sec (ar citi „blocat"), ci opunem rezistență tot
   * mai mare: se simte că mai poți trage, dar că nu mai e nimic acolo.
   */
  function rubberband(overshoot, dimension, constant) {
    var c = constant === undefined ? 0.55 : constant;
    return (overshoot * dimension * c) / (dimension + c * Math.abs(overshoot));
  }

  function clampWithResistance(x) {
    var lo = minOffset();
    var hi = maxOffset();
    var dim = root.clientWidth || 1;
    if (x > hi) return hi + rubberband(x - hi, dim);
    if (x < lo) return lo - rubberband(lo - x, dim);
    return x;
  }

  /* ── Starea vizibilă ───────────────────────────────────────────────────── */

  function setIndex(i, opts) {
    var next = Math.max(0, Math.min(slides.length - 1, i));
    index = next;
    for (var d = 0; d < dots.length; d++) {
      dots[d].setAttribute('aria-selected', d === next ? 'true' : 'false');
    }
    if (caption) caption.textContent = slides[next].getAttribute('data-caption') || '';
    syncArrows(next);
    for (var s = 0; s < slides.length; s++) {
      slides[s].setAttribute('aria-hidden', s === next ? 'false' : 'true');
    }
    if (!opts || !opts.silent) {
      spring.target = offsetFor(next);
      // Bounce DOAR când gestul a purtat moment. O depășire pe o săgeată de
      // tastatură ar fi zgomot; pe o azvârlire e exact ce se așteaptă mâna.
      spring.zeta = opts && opts.momentum ? 0.8 : 1.0;
      spring.omega = (2 * Math.PI) / (opts && opts.momentum ? 0.4 : 0.35);
      if (opts && typeof opts.velocity === 'number') spring.velocity = opts.velocity;
      run();
    }
  }

  /* ── Gestul ────────────────────────────────────────────────────────────── */

  var dragging = false;
  var pointerId = null;
  var startX = 0;
  var startOffset = 0;
  var committed = false;   // am depășit pragul de histerezis?
  var history = [];        // ultimele poziții+timp, pentru viteză la eliberare
  var THRESHOLD = 10;      // px înainte să ne hotărâm că e o tragere

  track.addEventListener('pointerdown', function (e) {
    if (e.button !== undefined && e.button !== 0) return;
    dragging = true;
    committed = false;
    pointerId = e.pointerId;
    startX = e.clientX;
    // Pornim din valoarea DE PE ECRAN, nu din țintă: dacă utilizatorul apucă
    // un carusel în mișcare, nu trebuie să sară nimic.
    stop();
    startOffset = spring.value;
    history = [{ x: e.clientX, t: performance.now() }];
    track.setPointerCapture(pointerId);
  });

  track.addEventListener('pointermove', function (e) {
    if (!dragging || e.pointerId !== pointerId) return;
    var dx = e.clientX - startX;

    if (!committed) {
      if (Math.abs(dx) < THRESHOLD) return;
      committed = true;
      // Reluăm originea din pragul depășit, ca degetul să nu „sară" cu 10px.
      startX = e.clientX - (dx > 0 ? THRESHOLD : -THRESHOLD);
      dx = e.clientX - startX;
    }

    history.push({ x: e.clientX, t: performance.now() });
    if (history.length > 6) history.shift();

    // 1:1 cu degetul, cu rezistență doar dincolo de capete.
    var raw = startOffset + dx;
    paint(clampWithResistance(raw));
    spring.value = clampWithResistance(raw);
    spring.velocity = 0;
  });

  function endDrag(e) {
    if (!dragging || (e && e.pointerId !== pointerId)) return;
    dragging = false;
    if (pointerId !== null && track.hasPointerCapture && track.hasPointerCapture(pointerId)) {
      track.releasePointerCapture(pointerId);
    }
    pointerId = null;

    if (!committed) {
      // O azvârlire foarte scurtă și foarte rapidă poate ajunge aici cu prea
      // puține evenimente de mișcare ca să fi trecut pragul în timpul
      // gestului. Distanța totală, măsurată la ridicarea degetului, spune
      // adevărul: dacă degetul chiar a parcurs drumul, a fost o tragere.
      var total = e ? Math.abs(e.clientX - startX) : 0;
      if (total < THRESHOLD) return; // a fost o atingere
      committed = true;
      history.push({ x: e.clientX, t: performance.now() });
    }

    // Viteza din ultimele mișcări (nu doar ultimul punct: un singur eșantion
    // e zgomot), în px/s.
    var v = 0;
    if (history.length >= 2) {
      var a = history[0];
      var b = history[history.length - 1];
      var dt = (b.t - a.t) / 1000;
      if (dt > 0.001) v = (b.x - a.x) / dt;
    }

    var projected = spring.value + project(v);
    var target = nearestIndex(projected);

    // Predarea vitezei: arcul pornește exact cu viteza degetului, ca să nu
    // existe o cusătură vizibilă între tragere și animație.
    setIndex(target, { momentum: Math.abs(v) > 80, velocity: v });
  }

  track.addEventListener('pointerup', endDrag);
  track.addEventListener('pointercancel', endDrag);

  // Un clic pe o captură vecină o aduce în centru — dar numai dacă n-a fost
  // o tragere (altfel fiecare glisare s-ar termina cu un salt nedorit).
  slides.forEach(function (slide, i) {
    slide.addEventListener('click', function () {
      if (committed) return;
      if (i !== index) setIndex(i);
    });
  });

  dots.forEach(function (dot, i) {
    dot.addEventListener('click', function () { setIndex(i); });
  });

  /* ── Săgețile ────────────────────────────────────────────────────────────
   * Aceeași stare ca punctele, altă unealtă: pentru mouse și pentru cine nu
   * ghicește că imaginea se trage. Săgeata care n-ar duce nicăieri dispare.
   */
  var arrows = Array.prototype.slice.call(root.querySelectorAll('.shots-arrow'));

  function syncArrows(i) {
    arrows.forEach(function (a) {
      var atEnd = a.getAttribute('data-side') === 'prev'
        ? i <= 0
        : i >= slides.length - 1;
      a.setAttribute('aria-disabled', atEnd ? 'true' : 'false');
    });
  }

  arrows.forEach(function (a) {
    a.addEventListener('click', function () {
      if (a.getAttribute('aria-disabled') === 'true') return;
      setIndex(index + (a.getAttribute('data-side') === 'prev' ? -1 : 1));
    });
  });

  root.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowRight') { e.preventDefault(); setIndex(index + 1); }
    if (e.key === 'ArrowLeft') { e.preventDefault(); setIndex(index - 1); }
  });

  var resizeTimer = null;
  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      stop();
      spring.value = spring.target = offsetFor(index);
      paint(spring.value);
    }, 120);
  });

  // Poziția inițială, fără animație.
  requestAnimationFrame(function () {
    spring.value = spring.target = offsetFor(0);
    paint(spring.value);
    setIndex(0, { silent: true });
  });

  /* ── Varianta cu mișcare redusă ───────────────────────────────────────── */

  function bindDotsToScroll() {
    var cur = 0;
    var arrows = Array.prototype.slice.call(root.querySelectorAll('.shots-arrow'));
    arrows.forEach(function (a) {
      a.addEventListener('click', function () {
        if (a.getAttribute('aria-disabled') === 'true') return;
        var i = cur + (a.getAttribute('data-side') === 'prev' ? -1 : 1);
        i = Math.max(0, Math.min(slides.length - 1, i));
        slides[i].scrollIntoView({ block: 'nearest', inline: 'center' });
        mark(i);
      });
    });

    dots.forEach(function (dot, i) {
      dot.addEventListener('click', function () {
        slides[i].scrollIntoView({ block: 'nearest', inline: 'center' });
        mark(i);
      });
    });
    track.addEventListener('scroll', function () {
      var mid = track.scrollLeft + track.clientWidth / 2;
      var best = 0, bestD = Infinity;
      slides.forEach(function (s, i) {
        var d = Math.abs(mid - (s.offsetLeft + s.offsetWidth / 2));
        if (d < bestD) { bestD = d; best = i; }
      });
      mark(best);
    }, { passive: true });
    mark(0);

    function mark(i) {
      cur = i;
      dots.forEach(function (d, n) {
        d.setAttribute('aria-selected', n === i ? 'true' : 'false');
      });
      if (caption) caption.textContent = slides[i].getAttribute('data-caption') || '';
      arrows.forEach(function (a) {
        var atEnd = a.getAttribute('data-side') === 'prev'
          ? i <= 0
          : i >= slides.length - 1;
        a.setAttribute('aria-disabled', atEnd ? 'true' : 'false');
      });
    }
  }
})();

/* Bara de sus capătă separare doar când există conținut pe dedesubt. */
(function () {
  var nav = document.querySelector('.nav');
  if (!nav) return;
  function sync() {
    nav.setAttribute('data-scrolled', window.scrollY > 8 ? 'true' : 'false');
  }
  window.addEventListener('scroll', sync, { passive: true });
  sync();
})();

/* Comutatorul de temă. Alegerea manuală bate sistemul și rămâne memorată;
   fără ea, pagina urmează tema telefonului, ca până acum. Comută o singură
   proprietate (`color-scheme`), restul paletei vine din `light-dark()`. */
(function () {
  var btn = document.getElementById('theme-toggle');
  if (!btn) return;

  var root = document.documentElement;
  var system = window.matchMedia('(prefers-color-scheme: dark)');
  var BAR = { light: '#415f91', dark: '#0d1420' };

  function resolved() {
    return root.dataset.theme || (system.matches ? 'dark' : 'light');
  }

  function sync() {
    var dark = resolved() === 'dark';
    // Iconița arată UNDE duce apăsarea, nu unde ești.
    btn.setAttribute('data-icon', dark ? 'sun' : 'moon');
    btn.setAttribute('aria-label', dark ? 'Treci pe tema deschisă' : 'Treci pe tema închisă');

    // Culoarea barei browserului pe telefon: cele două meta-uri sunt legate de
    // tema SISTEMULUI, deci după o alegere manuală ar rămâne pe cealaltă temă.
    if (root.dataset.theme) {
      var metas = document.querySelectorAll('meta[name="theme-color"]');
      for (var i = 0; i < metas.length; i++) {
        metas[i].removeAttribute('media');
        metas[i].setAttribute('content', dark ? BAR.dark : BAR.light);
      }
    }
  }

  btn.addEventListener('click', function () {
    var next = resolved() === 'dark' ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('tema', next); } catch (e) {}
    sync();
  });

  // Cât timp n-a ales nimeni manual, schimbarea temei sistemului se vede.
  system.addEventListener('change', sync);
  sync();
})();
